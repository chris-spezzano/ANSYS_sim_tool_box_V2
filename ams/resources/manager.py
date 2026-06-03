"""
Resource Manager — CPU/RAM allocation, license awareness, and zombie cleanup.

"Zombie" ANSYS processes are MAPDL or AEDT instances left running after a
crashed or interrupted simulation.  They hold gRPC ports (default 50052),
ANSYS license tokens, and RAM.  A new simulation launched while zombies are
alive will either fail to acquire a port or stall waiting for a license.

This module provides:
  - kill_ansys_zombies()  : terminate all stale ANSYS processes
  - ResourceManager       : recommend CPU/RAM settings from system inventory
  - estimate_memory()     : mesh-size-to-RAM rule-of-thumb
  - check_ports()         : report which gRPC ports are occupied
"""

from __future__ import annotations

import logging
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# ── Process names to target when killing zombies ──────────────────────────────
# These are the executable names as seen in the OS process table.
_MAPDL_PROC_NAMES   = {"ansys252", "ansys251", "ansys242", "ansys241", "ansys232",
                        "ansys231", "ansysedt", "mapdl"}
_AEDT_PROC_NAMES    = {"ansysedt", "aedt", "hfss", "q3d", "maxwell", "icepak"}
_GRPC_SERVER_NAMES  = {"apdl_grpc_server", "grpc_server", "mapdl_server"}

# Combined set — anything that might hold a port or license
_ALL_ANSYS_NAMES = _MAPDL_PROC_NAMES | _AEDT_PROC_NAMES | _GRPC_SERVER_NAMES


# ── Default gRPC port ranges ──────────────────────────────────────────────────
_MAPDL_PORTS = list(range(50052, 50062))   # PyMAPDL default: 50052
_AEDT_PORTS  = list(range(50051, 50055))   # PyAEDT  default: 50051


# ─────────────────────────────────────────────────────────────────────────────
# Public API — zombie cleanup
# ─────────────────────────────────────────────────────────────────────────────

def kill_ansys_zombies(
    dry_run: bool = False,
    include_aedt: bool = True,
    verbose: bool = True,
) -> list[dict[str, Any]]:
    """Kill all stale ANSYS MAPDL and AEDT processes.

    Parameters
    ----------
    dry_run : bool
        If True, report what *would* be killed but do not actually kill anything.
        Use this first to audit the system without risk.
    include_aedt : bool
        Also kill ANSYS Electronics Desktop (AEDT/HFSS) processes.
        Set False if you have a live HFSS session you want to keep.
    verbose : bool
        Print a table of killed processes to stdout.

    Returns
    -------
    list[dict]
        One entry per process found, with keys: pid, name, cmdline, killed.

    Notes
    -----
    Why this is necessary
    ~~~~~~~~~~~~~~~~~~~~~
    When a simulation crashes or is interrupted (Ctrl-C, kernel restart, power
    outage), the ANSYS backend process keeps running.  It holds:
      - A gRPC port (e.g., 50052) — next launch_mapdl() call will fail with
        "OSError: [WinError 10048] Only one usage of each socket address"
      - An ANSYS license token — if you have a single-user license, you cannot
        start a second instance until the zombie releases its token.
      - RAM — MAPDL pre-allocates its -m memory buffer immediately at startup.

    Safe to run
    ~~~~~~~~~~~
    This function only kills processes whose executable name matches known
    ANSYS names.  It does NOT kill Python, Jupyter, VS Code, etc.
    If you have a live, running simulation you care about, use dry_run=True
    to verify before killing.
    """
    target_names = _MAPDL_PROC_NAMES.copy()
    if include_aedt:
        target_names |= _AEDT_PROC_NAMES | _GRPC_SERVER_NAMES

    found: list[dict[str, Any]] = []

    if platform.system() == "Windows":
        found = _find_processes_windows(target_names)
    else:
        found = _find_processes_unix(target_names)

    if not found:
        if verbose:
            print("No ANSYS zombie processes found.")
        return []

    if verbose:
        _print_process_table(found, dry_run)

    for proc in found:
        if dry_run:
            proc["killed"] = False
            continue
        pid = proc["pid"]
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.kill(pid, 9)
            proc["killed"] = True
            log.info("Killed zombie PID %d (%s)", pid, proc["name"])
        except (PermissionError, ProcessLookupError, subprocess.TimeoutExpired) as exc:
            proc["killed"] = False
            log.warning("Could not kill PID %d: %s", pid, exc)

    if not dry_run:
        time.sleep(1.5)   # allow OS to release ports before next launch_mapdl()

    killed_count = sum(1 for p in found if p.get("killed"))
    if verbose and not dry_run:
        print(f"\nKilled {killed_count}/{len(found)} zombie processes.")
        if killed_count > 0:
            print("Waiting 1.5 s for ports to close...")

    return found


def check_ports(ports: list[int] | None = None) -> dict[int, bool]:
    """Check which gRPC ports are currently in use.

    Parameters
    ----------
    ports : list[int] | None
        Ports to probe.  Defaults to all MAPDL + AEDT default ports.

    Returns
    -------
    dict[int, bool]
        {port: is_occupied}.  True = something is listening on that port.

    Example
    -------
    >>> status = check_ports()
    >>> occupied = [p for p, used in status.items() if used]
    >>> print("Occupied ports:", occupied)
    """
    if ports is None:
        ports = _MAPDL_PORTS + _AEDT_PORTS

    result: dict[int, bool] = {}
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        occupied = sock.connect_ex(("127.0.0.1", port)) == 0
        sock.close()
        result[port] = occupied
        log.debug("Port %d: %s", port, "OCCUPIED" if occupied else "free")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# ResourceManager
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SystemInfo:
    """Snapshot of the current machine's resources."""
    total_ram_mb:     int
    available_ram_mb: int
    logical_cpus:     int
    physical_cpus:    int
    os_name:          str
    ansys_version:    str | None = None
    occupied_ports:   dict[int, bool] = field(default_factory=dict)


@dataclass
class ResourceRecommendation:
    """Recommended MAPDL / AEDT resource settings for a given problem."""
    nproc:        int       # number of parallel CPUs to use
    ram_mb:       int       # MAPDL -m memory allocation (MB)
    mapdl_port:   int       # first available port in 50052+
    aedt_port:    int       # first available AEDT port
    warnings:     list[str] = field(default_factory=list)
    rationale:    dict[str, str] = field(default_factory=dict)


class ResourceManager:
    """Query system resources and recommend MAPDL / AEDT settings.

    Usage
    -----
    >>> rm = ResourceManager()
    >>> info = rm.system_info()
    >>> rec  = rm.recommend(n_elements=50_000, has_hpc_license=False)
    >>> print(f"Use nproc={rec.nproc}, ram_mb={rec.ram_mb}, port={rec.mapdl_port}")

    The rule-of-thumb for MAPDL memory allocation
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    MAPDL pre-allocates its working memory at startup with the -m flag
    (set via launch_mapdl(ram=...)).  The required size depends on:
      - Number of DOFs  (≈ 3 × n_nodes for 3D structural)
      - Fill factor of the global stiffness matrix (depends on element type and connectivity)
      - Number of stored result sets (OUTRES,ALL,ALL stores every substep)

    Empirical rule:    ram_mb ≈ 15 × (n_elements / 1000) MB
    Conservative rule: ram_mb ≈ 25 × (n_elements / 1000) MB

    For a 50 000-element mesh: ~750 MB (empirical), ~1 250 MB (conservative).
    MAPDL will write to disk if it runs out of RAM, which is ~100× slower.

    License tokens
    ~~~~~~~~~~~~~~
    - nproc > 1 requires one ANSYS HPC license token per extra core.
    - Without an HPC license, set nproc=1 (default).
    - ANSYS Mechanical Enterprise includes 4 HPC tokens by default.
    """

    def __init__(self):
        self._info: SystemInfo | None = None

    def system_info(self, scan_ports: bool = True) -> SystemInfo:
        """Query current system resources.  Result is cached after first call."""
        if self._info is not None:
            return self._info

        try:
            import psutil
            total   = int(psutil.virtual_memory().total   / 1024**2)
            avail   = int(psutil.virtual_memory().available / 1024**2)
            logical = psutil.cpu_count(logical=True) or 1
            physical = psutil.cpu_count(logical=False) or 1
        except ImportError:
            total    = 8192
            avail    = 4096
            logical  = os.cpu_count() or 4
            physical = max(1, logical // 2)
            log.warning(
                "psutil not installed — using fallback resource estimates. "
                "Install it: pip install psutil"
            )

        ports = check_ports() if scan_ports else {}

        self._info = SystemInfo(
            total_ram_mb     = total,
            available_ram_mb = avail,
            logical_cpus     = logical,
            physical_cpus    = physical,
            os_name          = platform.system(),
            ansys_version    = _detect_ansys_version(),
            occupied_ports   = ports,
        )
        return self._info

    def recommend(
        self,
        n_elements: int = 10_000,
        has_hpc_license: bool = False,
        reserve_ram_fraction: float = 0.30,
    ) -> ResourceRecommendation:
        """Return recommended nproc, RAM, and ports for the given problem size.

        Parameters
        ----------
        n_elements : int
            Expected total element count (from mesh or estimate).
        has_hpc_license : bool
            Whether an ANSYS HPC parallel license is available.
        reserve_ram_fraction : float
            Fraction of available RAM to keep free for the OS and other apps.
            Default 0.30 means 30% of available RAM is held back.
        """
        info = self.system_info()
        warnings: list[str] = []
        rationale: dict[str, str] = {}

        # ── CPU recommendation ────────────────────────────────────────────────
        if has_hpc_license:
            nproc = min(info.physical_cpus, 8)
            rationale["nproc"] = (
                f"HPC license available; using {nproc} physical cores "
                f"(system has {info.physical_cpus})."
            )
        else:
            nproc = 1
            rationale["nproc"] = (
                "No HPC license — single-process mode (nproc=1). "
                "Set has_hpc_license=True and ensure an HPC token is available "
                "to enable parallel solve."
            )

        # ── RAM recommendation ────────────────────────────────────────────────
        empirical_mb   = max(512, int(15 * n_elements / 1000))
        conservative_mb = max(512, int(25 * n_elements / 1000))
        available_budget = int(info.available_ram_mb * (1 - reserve_ram_fraction))

        ram_mb = min(conservative_mb, available_budget)
        ram_mb = max(512, ram_mb)

        if conservative_mb > available_budget:
            warnings.append(
                f"Conservative RAM estimate ({conservative_mb} MB) exceeds "
                f"available budget ({available_budget} MB, keeping "
                f"{int(reserve_ram_fraction*100)}% free). "
                "MAPDL may spill to disk, slowing the solve significantly. "
                "Consider reducing mesh density or closing other applications."
            )
        rationale["ram_mb"] = (
            f"Empirical estimate: ~{empirical_mb} MB. "
            f"Conservative estimate: ~{conservative_mb} MB. "
            f"Allocated: {ram_mb} MB (capped to {int((1-reserve_ram_fraction)*100)}% "
            f"of available {info.available_ram_mb} MB)."
        )

        # ── Port selection ────────────────────────────────────────────────────
        ports = info.occupied_ports
        mapdl_port = next(
            (p for p in _MAPDL_PORTS if not ports.get(p, False)), _MAPDL_PORTS[0]
        )
        aedt_port = next(
            (p for p in _AEDT_PORTS if not ports.get(p, False)), _AEDT_PORTS[0]
        )

        occupied = [p for p, used in ports.items() if used]
        if occupied:
            warnings.append(
                f"Ports {occupied} are currently occupied. "
                "If these are zombie processes, run kill_ansys_zombies() first. "
                "Recommended MAPDL port set to first free: {mapdl_port}."
            )

        return ResourceRecommendation(
            nproc      = nproc,
            ram_mb     = ram_mb,
            mapdl_port = mapdl_port,
            aedt_port  = aedt_port,
            warnings   = warnings,
            rationale  = rationale,
        )

    def print_report(self, n_elements: int = 10_000, has_hpc_license: bool = False):
        """Print a human-readable resource summary and recommendation."""
        info = self.system_info()
        rec  = self.recommend(n_elements, has_hpc_license)

        print("=" * 64)
        print("  ANSYS Simulation Toolbox — Resource Report")
        print("=" * 64)
        print(f"  OS             : {info.os_name}")
        print(f"  ANSYS version  : {info.ansys_version or 'not detected'}")
        print(f"  Physical CPUs  : {info.physical_cpus}")
        print(f"  Logical  CPUs  : {info.logical_cpus}")
        print(f"  Total RAM      : {info.total_ram_mb:,} MB")
        print(f"  Available RAM  : {info.available_ram_mb:,} MB")
        print()

        occ = {p: s for p, s in info.occupied_ports.items() if s}
        free = {p: s for p, s in info.occupied_ports.items() if not s}
        print(f"  Occupied ports : {list(occ.keys()) or 'none'}")
        print(f"  Free ports     : {list(free.keys())}")
        print()

        print("  RECOMMENDATION for {:,} elements:".format(n_elements))
        print(f"    nproc      = {rec.nproc}")
        print(f"    ram_mb     = {rec.ram_mb}")
        print(f"    mapdl_port = {rec.mapdl_port}")
        print(f"    aedt_port  = {rec.aedt_port}")
        print()

        if rec.warnings:
            print("  WARNINGS:")
            for w in rec.warnings:
                print(f"    [!] {w}")
            print()

        print("  RATIONALE:")
        for key, reason in rec.rationale.items():
            print(f"    {key}: {reason}")
        print("=" * 64)


# ─────────────────────────────────────────────────────────────────────────────
# Memory estimation helper
# ─────────────────────────────────────────────────────────────────────────────

def estimate_memory(
    n_elements: int,
    dofs_per_node: int = 3,
    nodes_per_element: int = 8,
    n_result_sets: int = 10,
) -> dict[str, int]:
    """Estimate MAPDL memory requirements (MB) for a given mesh.

    Parameters
    ----------
    n_elements : int
        Total element count.
    dofs_per_node : int
        Degrees of freedom per node.
        Structural 2D = 2, structural 3D = 3, thermal = 1.
    nodes_per_element : int
        Nodes per element (PLANE182=4, SOLID185=8, SOLID186=20, SHELL181=4).
    n_result_sets : int
        Number of result sets stored (affects RST file size, not RAM directly).

    Returns
    -------
    dict with keys: stiffness_mb, rhs_mb, results_mb, total_mb, conservative_mb

    Mathematical basis
    ------------------
    The global stiffness matrix [K] is assembled from element matrices.
    For a skyline (profile) solver:
        nnz ≈ dofs_per_node² × nodes_per_element × n_elements × fill_factor
    where fill_factor ≈ 0.5 for typical structured meshes.
    Memory: nnz × 8 bytes (double precision).

    RHS vector and solution vector: n_dof × 8 bytes each.
    MAPDL's overhead (pre-conditioner, Lanczos vectors, etc.): ~2× the matrix.
    """
    n_nodes     = n_elements * nodes_per_element // 4   # rough unique node estimate
    n_dof       = n_nodes * dofs_per_node
    fill_factor = 0.5
    nnz         = int(dofs_per_node**2 * nodes_per_element * n_elements * fill_factor)

    stiffness_mb  = int(nnz * 8 / 1024**2)
    rhs_mb        = int(n_dof * 8 * 4 / 1024**2)   # RHS, solution, residual, precond
    overhead_mb   = stiffness_mb                     # ~1× matrix for factored form
    total_mb      = stiffness_mb + rhs_mb + overhead_mb

    results_mb    = int(n_dof * 8 * n_result_sets / 1024**2)
    conservative_mb = max(512, int(total_mb * 1.5) + results_mb)

    return {
        "stiffness_mb":   max(64, stiffness_mb),
        "rhs_mb":         max(32, rhs_mb),
        "overhead_mb":    max(64, overhead_mb),
        "total_mb":       max(256, total_mb),
        "conservative_mb": conservative_mb,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_processes_windows(target_names: set[str]) -> list[dict[str, Any]]:
    """Return process info for all matching processes (Windows via psutil)."""
    found = []
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline", "status"]):
            try:
                name = (proc.info["name"] or "").lower()
                bare = name.replace(".exe", "")
                if bare in target_names or name in target_names:
                    found.append({
                        "pid":     proc.info["pid"],
                        "name":    proc.info["name"],
                        "cmdline": " ".join(proc.info["cmdline"] or [])[:120],
                        "status":  proc.info["status"],
                        "killed":  False,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        # Fallback: use tasklist
        try:
            out = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"], text=True, timeout=10
            )
            for line in out.strip().splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    name = parts[0].lower().replace(".exe", "")
                    if name in target_names:
                        try:
                            pid = int(parts[1])
                        except ValueError:
                            continue
                        found.append({
                            "pid": pid, "name": parts[0],
                            "cmdline": "", "status": "running", "killed": False,
                        })
        except Exception as exc:
            log.warning("tasklist fallback failed: %s", exc)
    return found


def _find_processes_unix(target_names: set[str]) -> list[dict[str, Any]]:
    """Return process info for all matching processes (Linux/macOS via psutil)."""
    found = []
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                if name in target_names:
                    found.append({
                        "pid":     proc.info["pid"],
                        "name":    proc.info["name"],
                        "cmdline": " ".join(proc.info["cmdline"] or [])[:120],
                        "status":  "running",
                        "killed":  False,
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except ImportError:
        try:
            out = subprocess.check_output(
                ["ps", "aux"], text=True, timeout=10
            )
            for line in out.strip().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 11:
                    cmd = parts[10].lower()
                    name = cmd.split("/")[-1]
                    if name in target_names:
                        found.append({
                            "pid": int(parts[1]), "name": name,
                            "cmdline": " ".join(parts[10:])[:120],
                            "status": parts[7], "killed": False,
                        })
        except Exception as exc:
            log.warning("ps fallback failed: %s", exc)
    return found


def _print_process_table(procs: list[dict], dry_run: bool) -> None:
    action = "Would kill" if dry_run else "Killing"
    print(f"\n  {action} {len(procs)} ANSYS process(es):")
    print(f"  {'PID':>8}  {'Name':<20}  {'Status':<12}  {'Command'}")
    print("  " + "-" * 70)
    for p in procs:
        cmd = p.get("cmdline", "")[:40]
        print(f"  {p['pid']:>8}  {p['name']:<20}  {p.get('status','?'):<12}  {cmd}")


def _detect_ansys_version() -> str | None:
    """Attempt to detect the installed ANSYS version from known Windows paths."""
    if platform.system() != "Windows":
        return None
    for version in ["252", "251", "242", "241", "232", "231"]:
        path = rf"D:\ANSYS Inc\v{version}\ansys\bin\winx64\ansys{version}.exe"
        if os.path.exists(path):
            return f"v{version}"
    return None
