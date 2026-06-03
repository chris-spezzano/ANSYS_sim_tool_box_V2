"""
HFSS / PyAEDT Runner — lifecycle management for ANSYS Electronics Desktop.

Encapsulates all the real-world gotchas learned from the origami EMI workflow:
  1. Always use non_graphical=True for automated pipelines (GUI hangs on server)
  2. Always use new_desktop=True to avoid stale setup state from prior runs
  3. Delete ALL stale project files (.aedt, .lock, .aedtresults/) before launch
  4. Kill zombie AEDT processes before launch_mapdl (they hold gRPC ports)
  5. Set desktop_launch_timeout high enough for license checkout (up to 600s)

Reference: D:/Projects/origami_emi_workflow/guide/03_HFSS_AEDT_CODING_GUIDE.md
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

from ..resources.manager import kill_ansys_zombies

log = logging.getLogger(__name__)


class HFSSRunner:
    """Create and manage a PyAEDT HFSS instance from a config dict.

    Parameters
    ----------
    cfg : dict
        The full toolbox config dict.  Only 'hfss' and 'resources' sub-dicts used.

    Example
    -------
    >>> runner = HFSSRunner(cfg)
    >>> hfss   = runner.connect()
    >>> # ... build model, assign BCs, solve ...
    >>> runner.disconnect()
    """

    def __init__(self, cfg: dict):
        self._cfg   = cfg
        self._hfss  = None

    def connect(self, kill_zombies: bool = True) -> Any:
        """Launch HFSS and return the active Hfss object.

        Parameters
        ----------
        kill_zombies : bool
            Kill stale AEDT processes before launch.  Recommended True.
        """
        hfss_cfg = self._cfg.get("hfss", {})

        if kill_zombies:
            log.info("Clearing AEDT zombie processes before launch…")
            kill_ansys_zombies(include_aedt=True, verbose=True)
            time.sleep(2.0)

        project_dir  = Path(self._cfg.get("output", {}).get("dir", "outputs")) / "hfss_project"
        project_dir.mkdir(parents=True, exist_ok=True)
        project_name = hfss_cfg.get("project_name", "ams_hfss")

        # Purge stale project files — CRITICAL (see module docstring #3)
        cleanup_hfss_project(project_dir, project_name)

        project_path = str(project_dir / f"{project_name}.aedt")
        aedt_version = hfss_cfg.get("aedt_version", "2025.2")
        non_graphical = bool(hfss_cfg.get("non_graphical", True))
        timeout       = int(hfss_cfg.get("desktop_launch_timeout_s", 600))

        log.info(
            "Launching HFSS %s — non_graphical=%s, project='%s'",
            aedt_version, non_graphical, project_name,
        )

        try:
            import ansys.aedt.core as aedt
            self._hfss = aedt.Hfss(
                project       = project_path,
                non_graphical = non_graphical,
                new_desktop   = True,        # always open fresh (see docstring #2)
                version       = aedt_version,
            )
            log.info("HFSS connected successfully")
        except Exception as exc:
            raise ConnectionError(
                f"Failed to launch HFSS {aedt_version}.\n"
                f"  Ensure ANSYS Electronics Desktop is installed.\n"
                f"  Check that the AEDT license server is reachable.\n"
                f"  Try kill_ansys_zombies(include_aedt=True) first.\n"
                f"  Original error: {exc}"
            ) from exc

        return self._hfss

    def disconnect(self, save: bool = True) -> None:
        """Save and close the HFSS project."""
        if self._hfss is None:
            return
        try:
            if save:
                self._hfss.save_project()
            self._hfss.release_desktop()
            log.info("HFSS desktop released")
        except Exception as exc:
            log.warning("Error during HFSS disconnect: %s", exc)
        finally:
            self._hfss = None

    @property
    def hfss(self):
        return self._hfss

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Pre-launch cleanup
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_hfss_project(project_dir: Path, project_name: str) -> None:
    """Delete stale HFSS project files before each run.

    Why this is essential
    ---------------------
    HFSS stores the adaptive pass counter in .aedtresults/.  If these files
    exist from a prior run:
      - HFSS may think 20 adaptive passes have already run and skip the solve, OR
      - Setup registration fails with duplicate setup ID errors.
    The lock file (.aedt.lock) prevents re-opening the project if a prior
    Electronics Desktop session did not exit cleanly.

    Files deleted
    -------------
    - {name}.aedt          — main project file
    - {name}.aedt.auto     — auto-save backup
    - {name}.aedtresults/  — solver results directory (adaptive pass counter)
    - {name}.lock          — session lock file
    """
    to_delete = [
        project_dir / f"{project_name}.aedt",
        project_dir / f"{project_name}.aedt.auto",
        project_dir / f"{project_name}.lock",
    ]
    results_dir = project_dir / f"{project_name}.aedtresults"

    deleted: list[str] = []
    for p in to_delete:
        if p.exists():
            p.unlink()
            deleted.append(p.name)

    if results_dir.exists():
        shutil.rmtree(results_dir)
        deleted.append(f"{project_name}.aedtresults/")

    if deleted:
        log.info("Cleaned up stale HFSS files: %s", deleted)
    else:
        log.debug("No stale HFSS files to clean up")
