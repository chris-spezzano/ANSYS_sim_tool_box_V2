"""
MAPDL Runner — lifecycle management for PyMAPDL connections.

Handles launch, reconnect, graceful shutdown, and crash recovery.
Encapsulates the connection pattern from the MAPDL toolbox while adding:
  - Automatic zombie cleanup before launch
  - Port availability verification
  - ANSYS version detection
  - Config-driven setup (no hardcoded paths)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..resources.manager import kill_ansys_zombies, check_ports

log = logging.getLogger(__name__)


class MAPDLRunner:
    """Create and manage a PyMAPDL instance from a config dict.

    Parameters
    ----------
    cfg : dict
        The full toolbox config dict (loaded from config.yaml).  Only the
        'mapdl' and 'resources' sub-dicts are used here.

    Example
    -------
    >>> from ams.mapdl.runner import MAPDLRunner
    >>> from ams.config import load_config
    >>> cfg = load_config("config.yaml")
    >>> runner = MAPDLRunner(cfg)
    >>> mapdl = runner.connect()
    >>> # ... build, solve, post-process ...
    >>> runner.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg     = cfg
        self._mapdl   = None
        self._owns_it = False   # True if we launched the instance (we must exit it)

    def connect(self, kill_zombies: bool = True) -> Any:
        """Connect to (or launch) a MAPDL instance.

        Parameters
        ----------
        kill_zombies : bool
            Run kill_ansys_zombies() before launching to clear stale processes
            that might block the port.  Recommended True for scripted workflows.

        Returns
        -------
        PyMAPDL Mapdl instance ready for use.
        """
        mapdl_cfg = self._cfg.get("mapdl", {})

        if kill_zombies and mapdl_cfg.get("start_instance", True):
            log.info("Clearing ANSYS zombie processes before launch…")
            killed = kill_ansys_zombies(include_aedt=False, verbose=True)
            if killed:
                import time
                time.sleep(1.5)

        self._mapdl   = _connect(mapdl_cfg, self._cfg.get("resources", {}))
        self._owns_it = mapdl_cfg.get("start_instance", True)
        return self._mapdl

    def disconnect(self, save_project: bool = False) -> None:
        """Gracefully shut down the MAPDL instance if we own it."""
        if self._mapdl is None:
            return
        try:
            if save_project:
                self._mapdl.save()
            if self._owns_it:
                self._mapdl.exit()
                log.info("MAPDL instance exited cleanly")
        except Exception as exc:
            log.warning("Error during MAPDL disconnect: %s", exc)
        finally:
            self._mapdl = None

    @property
    def mapdl(self):
        """Access the live MAPDL instance (None if not connected)."""
        return self._mapdl

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Internal connection logic
# ─────────────────────────────────────────────────────────────────────────────

def _connect(mapdl_cfg: dict, resources_cfg: dict) -> Any:
    """Launch or connect to MAPDL according to the config."""
    from ansys.mapdl.core import launch_mapdl

    start_instance: bool = mapdl_cfg.get("start_instance", True)
    port:           int  = int(mapdl_cfg.get("port", 50052))
    nproc:          int  = int(resources_cfg.get("max_nproc", 1))
    ram_mb:         int  = int(mapdl_cfg.get("ram_mb", resources_cfg.get("max_ram_mb", 2048)))

    kwargs: dict[str, Any] = {
        "start_instance": start_instance,
        "port":           port,
        "start_timeout":  int(mapdl_cfg.get("timeout", 120)),
        "loglevel":       mapdl_cfg.get("loglevel", "WARNING"),
    }

    if start_instance:
        # Set binary path if provided; fallback to auto-detect
        binary = mapdl_cfg.get("custom_bin") or _detect_ansys_binary()
        if binary:
            kwargs["exec_file"] = binary

        # Working directory for MAPDL scratch files
        run_loc = mapdl_cfg.get("run_location")
        if run_loc:
            Path(run_loc).mkdir(parents=True, exist_ok=True)
            kwargs["run_location"] = str(run_loc)

        # Job name
        jobname = mapdl_cfg.get("jobname", "ams_run")
        kwargs["jobname"] = jobname

        # CPU cores
        kwargs["nproc"] = nproc

        # RAM allocation (-m flag in MAPDL)
        kwargs["ram"] = ram_mb

        # Headless mode — suppress MAPDL GUI window
        if not mapdl_cfg.get("show_gui", False):
            kwargs["additional_switches"] = "-g"

        # USERMAT DLL — set ANS_USER_PATH so MAPDL loads it at startup
        usermat_dll = mapdl_cfg.get("usermat_dll")
        if usermat_dll:
            dll_dir = str(Path(usermat_dll).parent)
            os.environ["ANS_USER_PATH"] = dll_dir
            log.info("ANS_USER_PATH set to: %s", dll_dir)

        # Port availability check
        ports = check_ports([port])
        if ports.get(port):
            log.warning(
                "Port %d is already occupied.  "
                "Another MAPDL instance may be running.  "
                "Run kill_ansys_zombies() first, or change the port in config.yaml.",
                port,
            )

        log.info(
            "Launching MAPDL: binary=%s, port=%d, nproc=%d, ram=%d MB, jobname=%s",
            binary or "auto", port, nproc, ram_mb, jobname,
        )

    else:
        # Connecting to an already-running instance
        kwargs["ip"]   = "127.0.0.1"
        log.info("Connecting to running MAPDL at 127.0.0.1:%d", port)

    try:
        return launch_mapdl(**kwargs)
    except Exception as exc:
        raise ConnectionError(
            f"Failed to connect to MAPDL on port {port}.\n"
            f"  If start_instance=true: ensure the ANSYS executable exists at '{kwargs.get('exec_file', 'auto')}'\n"
            f"  If start_instance=false: start MAPDL manually first.\n"
            f"  Run kill_ansys_zombies() if port {port} is already occupied.\n"
            f"  Original error: {exc}"
        ) from exc


def _detect_ansys_binary() -> str | None:
    """Search known installation paths for an ANSYS executable (Windows)."""
    import platform
    if platform.system() != "Windows":
        return None
    for ver in ["252", "251", "242", "241", "232"]:
        for drive in ["D:", "C:"]:
            p = rf"{drive}\ANSYS Inc\v{ver}\ansys\bin\winx64\ansys{ver}.exe"
            if os.path.exists(p):
                log.info("Auto-detected ANSYS binary: %s", p)
                return p
    return None
