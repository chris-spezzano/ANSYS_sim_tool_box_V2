"""
nTopology Automation Driver — run .ntop files from Python with YAML-driven
parameter overrides, enabling fully scripted geometry generation and
parametric sweeps without opening the nTopology GUI.

nTopology CLI overview
----------------------
nTopology 5.x ships a headless runner:

    ntopology.exe --headless --run <file.ntop>
                  [--json-input <params.json>]
                  [--output <export_dir>]

Parameter overrides are passed via a JSON input file that maps Input Block
names (exactly as they appear in the .ntop workflow tree) to new values.

JSON parameter file format
--------------------------
{
  "inputs": {
    "Plate Size X":       70.0,
    "Plate Size Y":       70.0,
    "Plate Thickness":     3.0,
    "Trough Depth":        1.6,
    "Trough Width":        2.0,
    "Mesh Tolerance":      1.0
  }
}

Values can be:
  - Scalar (float/int):  {"Mesh Tolerance": 1.0}
  - Vector (list):       {"Trough Translation": [0.0, 0.0, 1.6]}
  - Boolean:             {"Sharpen": true}

Units are controlled by the Input Block definition inside .ntop — confirm the
expected unit (mm vs m) in the nTop workflow tree before writing this file.

Export blocks in the .ntop file
--------------------------------
For the CDB to appear in --output, add an "Export" block at the end of the
Waterbomb.ntop workflow:
  Block type : Export > FEA Mesh > Ansys CDB
  File path  : Use a relative path like "waterbomb_mesh.cdb" — nTop resolves
               this relative to the --output directory.

Named component export (recommended for BC targeting)
------------------------------------------------------
Add "Export > Named Selection" blocks in nTop to tag:
  - CREASE_VERT    : nodes on x = plate_cx (vertical crease)
  - CREASE_HORIZ   : nodes on y = plate_cy (horizontal crease)
  - CREASE_DIAG_P  : nodes on the +45° diagonal
  - CREASE_DIAG_N  : nodes on the -45° diagonal
  - OUTER_CORNERS  : nodes at the 4 plate corners
  - CENTER_PATCH   : nodes within r < 2 mm of plate center

These component names are preserved in the .cdb and can be referenced
directly in MAPDL via CMSEL — see origami_bcs.py.

If named components are not exported, origami_bcs.py falls back to
coordinate-based node selection (slower but always works).
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from shutil import which
from typing import Any

log = logging.getLogger(__name__)

_NTOP_EXE_CANDIDATES = [
    r"C:\Program Files\nTopology\ntopology.exe",
    r"C:\Program Files (x86)\nTopology\ntopology.exe",
    r"C:\nTopology\ntopology.exe",
    r"C:\ProgramData\nTopology\ntopology.exe",
]


class NTopDriver:
    """Drive nTopology geometry generation headlessly from Python.

    Parameters
    ----------
    executable : str | Path | None
        Full path to ntopology.exe.  If None, searches standard install paths
        and the system PATH.
    timeout_s : int
        Maximum wall-clock seconds to wait for nTop to exit.  Default 300 (5 min).
        Increase for large meshes or slow machines.

    Example
    -------
    >>> driver = NTopDriver()
    >>> outputs = driver.run(
    ...     project    = "Waterbomb.ntop",
    ...     parameters = {
    ...         "Plate Size X":   70.0,   # mm
    ...         "Plate Size Y":   70.0,   # mm
    ...         "Trough Depth":    1.6,   # mm  — controls crease sharpness
    ...         "Mesh Tolerance":  1.0,   # mm  — drives nTop mesh density
    ...     },
    ...     export_dir       = "outputs/geometry/iter_001",
    ...     expected_outputs = ["*.cdb"],
    ... )
    >>> cdb_path = outputs["*.cdb"]
    """

    def __init__(
        self,
        executable: str | Path | None = None,
        timeout_s: int = 300,
    ):
        self._exe     = self._resolve_executable(executable)
        self._timeout = timeout_s

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        project: str | Path,
        parameters: dict[str, Any] | None = None,
        export_dir: str | Path = "ntop_exports",
        expected_outputs: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> dict[str, Path]:
        """Run an nTopology project file with optional parameter overrides.

        Parameters
        ----------
        project : str | Path
            Path to the .ntop file.
        parameters : dict[str, Any] | None
            Block name → value overrides.  Keys must match Input Block names
            exactly as they appear in the nTop workflow tree.
        export_dir : str | Path
            Directory where nTop writes exported CDB/STL files.
        expected_outputs : list[str] | None
            Glob patterns to wait for, e.g., ``["*.cdb"]``.  The driver polls
            the export directory until all patterns are satisfied.
            Pass None to return immediately after nTop exits.
        extra_args : list[str] | None
            Extra flags forwarded verbatim to ntopology.exe, e.g.
            ``["--license-server", "my-server:1055"]``.

        Returns
        -------
        dict[str, Path]
            Maps each expected glob pattern to the matched file Path.

        Raises
        ------
        FileNotFoundError
            .ntop project file not found.
        subprocess.CalledProcessError
            ntopology.exe returned a non-zero exit code.
        TimeoutError
            Expected output files did not appear within timeout_s.
        """
        project_path = Path(project).resolve()
        if not project_path.exists():
            raise FileNotFoundError(f"nTop project not found: {project_path}")

        export_path = Path(export_dir).resolve()
        export_path.mkdir(parents=True, exist_ok=True)

        # Write parameter override file
        param_file: Path | None = None
        if parameters:
            param_file = export_path / "_ntop_params.json"
            self._write_params(parameters, param_file)

        cmd = [
            str(self._exe),
            "--headless",
            "--run",    str(project_path),
            "--output", str(export_path),
        ]
        if param_file:
            cmd += ["--json-input", str(param_file)]
        if extra_args:
            cmd.extend(extra_args)

        log.info("nTopology command: %s", " ".join(cmd))
        print(f"\nnTopology: running {project_path.name}")
        print(f"  Parameters : {parameters or 'default'}")
        print(f"  Export dir : {export_path}")

        t0 = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        elapsed = time.time() - t0

        if proc.returncode != 0:
            log.error("nTop stdout:\n%s", proc.stdout[-4000:])
            log.error("nTop stderr:\n%s", proc.stderr[-4000:])
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, proc.stdout, proc.stderr
            )

        log.info("nTopology finished in %.1f s", elapsed)
        print(f"  Done in {elapsed:.1f} s")

        if not expected_outputs:
            return {}

        return self._collect_outputs(export_path, expected_outputs)

    def run_sweep(
        self,
        project: str | Path,
        param_sets: list[dict[str, Any]],
        base_export_dir: str | Path = "ntop_exports",
        expected_outputs: list[str] | None = None,
    ) -> list[dict[str, Path]]:
        """Run the same .ntop project for each parameter set in a sweep.

        Each run gets its own subdirectory ``sweep_NNNN`` so outputs never
        collide.  Suitable for driving the ``SimulationPipeline.sweep()`` flow.

        Parameters
        ----------
        project : str | Path
            Path to the .ntop project file.
        param_sets : list[dict]
            One dict per sweep point, e.g.::

                [
                    {"Trough Depth": 1.0, "Mesh Tolerance": 0.5},
                    {"Trough Depth": 1.5, "Mesh Tolerance": 0.5},
                    {"Trough Depth": 2.0, "Mesh Tolerance": 0.5},
                ]

        base_export_dir : str | Path
            Root directory; each run is placed in ``sweep_NNNN``.
        expected_outputs : list[str] | None
            Glob patterns for files to wait for.

        Returns
        -------
        list[dict[str, Path]]
            One output dict per sweep point.
        """
        results = []
        for i, params in enumerate(param_sets):
            export_dir = Path(base_export_dir) / f"sweep_{i:04d}"
            log.info("Sweep %d/%d: %s", i + 1, len(param_sets), params)
            outputs = self.run(
                project          = project,
                parameters       = params,
                export_dir       = export_dir,
                expected_outputs = expected_outputs,
            )
            results.append(outputs)
        return results

    # ── Internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _write_params(parameters: dict[str, Any], path: Path) -> None:
        """Serialise parameters to the nTop JSON input file format."""
        payload = {"inputs": {k: v for k, v in parameters.items()}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.debug("nTop parameter file written → %s  (%d params)", path, len(parameters))

    def _collect_outputs(
        self,
        export_dir: Path,
        patterns: list[str],
        poll_interval_s: float = 2.0,
    ) -> dict[str, Path]:
        """Poll export_dir until every glob pattern has a matching file."""
        deadline = time.time() + self._timeout
        found: dict[str, Path] = {}

        while time.time() < deadline:
            for pattern in patterns:
                if pattern in found:
                    continue
                matches = sorted(export_dir.glob(pattern))
                if matches:
                    found[pattern] = matches[-1]   # latest match

            if len(found) == len(patterns):
                return found

            time.sleep(poll_interval_s)

        missing = [p for p in patterns if p not in found]
        raise TimeoutError(
            f"nTop outputs not found after {self._timeout}s: {missing}\n"
            f"  Check that the Export blocks in your .ntop file write to the\n"
            f"  --output directory, and that the file names match: {missing}\n"
            f"  Export dir: {export_dir}"
        )

    @staticmethod
    def _resolve_executable(exe: str | Path | None) -> Path:
        if exe:
            p = Path(exe)
            if not p.exists():
                raise FileNotFoundError(f"ntopology.exe not found at: {p}")
            return p

        for candidate in _NTOP_EXE_CANDIDATES:
            p = Path(candidate)
            if p.exists():
                return p

        w = which("ntopology")
        if w:
            return Path(w)

        raise FileNotFoundError(
            "ntopology.exe not found.\n"
            "Set ntop.executable in your YAML config, or verify that nTopology\n"
            "is installed to one of the standard paths:\n"
            + "\n".join(f"  {c}" for c in _NTOP_EXE_CANDIDATES)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Config-driven entry point (called by pipeline stage run_fn)
# ─────────────────────────────────────────────────────────────────────────────

def run_ntop_from_config(cfg: dict) -> dict[str, str]:
    """Run nTopology geometry generation driven by the YAML config.

    This is the ``run_fn`` used by ``make_ntop_geometry_stage()``.

    YAML schema consumed (``ntop`` block)
    --------------------------------------
    .. code-block:: yaml

        ntop:
          executable: null          # path to ntopology.exe; null = auto-detect
          project: "Waterbomb.ntop" # path to the .ntop project file
          timeout_s: 300

          parameters:               # Input Block name → value (units = mm)
            Plate Size X:   70.0
            Plate Size Y:   70.0
            Plate Thickness: 3.0
            Trough Depth:    1.6
            Trough Width:    2.0
            Mesh Tolerance:  1.0

          export_dir: "outputs/geometry"
          expected_outputs:
            - "*.cdb"               # wait for a CDB file to appear

    Parameters
    ----------
    cfg : dict
        Full pipeline config dict (the ``ntop`` key is read here).

    Returns
    -------
    dict
        ``{"cdb_path": "...", "stl_path": "..."}`` — whichever formats were
        exported.  Downstream pipeline stages read these keys via input_map.
    """
    ntop_cfg = cfg.get("ntop", {})
    if not ntop_cfg:
        raise ValueError(
            "Config is missing the 'ntop' section.\n"
            "Add ntop.project, ntop.parameters, and ntop.export_dir."
        )

    driver = NTopDriver(
        executable = ntop_cfg.get("executable"),
        timeout_s  = int(ntop_cfg.get("timeout_s", 300)),
    )

    # nTopology 5.x Export FE Mesh writes Abaqus .inp, not .cdb.
    # Default to *.inp; legacy configs that set *.cdb still work if the file exists.
    expected = ntop_cfg.get("expected_outputs", ["*.inp"])
    outputs  = driver.run(
        project          = ntop_cfg["project"],
        parameters       = ntop_cfg.get("parameters", {}),
        export_dir       = ntop_cfg.get("export_dir", "outputs/geometry"),
        expected_outputs = expected,
    )

    result: dict[str, str] = {}
    for pattern, path in outputs.items():
        low = pattern.lower()
        if "cdb" in low:
            result["cdb_path"] = str(path)
        elif "inp" in low:
            # Abaqus .inp from nTopology — GeometryImporter.from_inp() converts
            # it to CDB via meshio before passing to MAPDL
            result["inp_path"] = str(path)
        elif "stl" in low:
            result["stl_path"] = str(path)
        elif "step" in low or "stp" in low:
            result["step_path"] = str(path)
        else:
            result[f"export_{pattern}"] = str(path)

    log.info("nTop geometry stage outputs: %s", result)
    return result
