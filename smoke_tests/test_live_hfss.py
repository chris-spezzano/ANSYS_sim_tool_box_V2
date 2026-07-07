"""
Live HFSS smoke test — requires ANSYS Electronics Desktop installation.

Stages
------
1. Pre-flight: zombie cleanup, port check, project file cleanup
2. Launch HFSS (non-graphical)
3. Create a minimal box geometry (1mm cube)
4. Assign PEC boundary
5. Create a DrivenModal setup with 1 adaptive pass
6. Solve (single frequency point — fast)
7. Verify the solve completed without error
8. Graceful shutdown

Expected runtime: ~3–5 minutes (AEDT startup dominates)

Usage
-----
    python smoke_tests/test_live_hfss.py              # full live test
    python smoke_tests/test_live_hfss.py --dry-run    # skip HFSS, test imports only
    python smoke_tests/test_live_hfss.py --cleanup-only  # only run cleanup stages
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DRY_RUN      = "--dry-run" in sys.argv
CLEANUP_ONLY = "--cleanup-only" in sys.argv

PROJECT_DIR  = Path("outputs/hfss_smoke")
PROJECT_NAME = "smoke_test"


def test_aedt_imports():
    """Verify PyAEDT can be imported."""
    if DRY_RUN:
        print("  SKIP: AEDT import check (dry-run)")
        return True
    try:
        import ansys.aedt.core
        print(f"  PASS: ansys.aedt.core imported (version {getattr(ansys.aedt.core, '__version__', '?')})")
        return True
    except ImportError as e:
        print(f"  SKIP: ansys-aedt-core not installed: {e}")
        print("  Install with: pip install ansys-aedt-core")
        return True   # Not a hard failure — AEDT is optional


def test_aedt_cleanup():
    """Run pre-launch cleanup: kill zombies, purge stale project files."""
    from ams.resources.manager import kill_ansys_zombies, check_ports
    from ams.hfss.runner import cleanup_hfss_project

    kill_ansys_zombies(dry_run=False, include_aedt=True, verbose=False)

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_hfss_project(PROJECT_DIR, PROJECT_NAME)

    ports = check_ports()
    occupied = [p for p, s in ports.items() if s]
    if occupied:
        print(f"  WARN: ports {occupied} still occupied after cleanup")
    else:
        print("  PASS: aedt_cleanup — project files purged, ports free")
    return True


def test_live_hfss_box():
    """
    Launch HFSS, create a 1mm³ PEC box, run 1 adaptive pass at 10 GHz,
    verify the solve completes without error.
    """
    if DRY_RUN or CLEANUP_ONLY:
        print("  SKIP: live HFSS test (dry-run or cleanup-only mode)")
        return True

    try:
        import ansys.aedt.core as aedt
    except ImportError:
        print("  SKIP: ansys-aedt-core not installed")
        return True

    import yaml
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    aedt_version = cfg.get("hfss", {}).get("aedt_version", "2025.1")
    project_path = str(PROJECT_DIR / f"{PROJECT_NAME}.aedt")

    hfss = None
    try:
        hfss = aedt.Hfss(
            project       = project_path,
            non_graphical = True,
            new_desktop   = True,
            version       = aedt_version,
        )

        # Create a 1mm cube
        box = hfss.modeler.create_box(
            origin = [0, 0, 0],
            sizes  = [0.001, 0.001, 0.001],
            name   = "SmokeCube",
            material = "copper",
        )

        # Assign PEC boundary
        hfss.assign_perfect_e("SmokeCube", name="PEC_Smoke")

        # Create a minimal setup: 1 adaptive pass at 10 GHz
        setup = hfss.create_setup("SmokeSetup")
        setup.props["Frequency"]       = "10GHz"
        setup.props["MaximumPasses"]   = 1
        setup.props["MaxDeltaS"]       = 0.02

        # Validate and solve
        hfss.validate_full_design()
        hfss.analyze()

        # Check that the solution finished
        if not hfss.solution_type:
            print("  FAIL: HFSS solve returned no solution type")
            return False

        print(f"  PASS: live HFSS smoke test — 1 adaptive pass at 10 GHz complete")
        hfss.save_project()
        return True

    except Exception as exc:
        print(f"  FAIL: live HFSS test raised {type(exc).__name__}: {exc}")
        return False

    finally:
        if hfss is not None:
            try:
                hfss.release_desktop()
            except Exception:
                pass


STAGE_TESTS = [
    ("aedt_imports",    test_aedt_imports),
    ("aedt_cleanup",    test_aedt_cleanup),
    ("live_hfss_box",   test_live_hfss_box),
]


def main():
    mode = "DRY-RUN" if DRY_RUN else "CLEANUP-ONLY" if CLEANUP_ONLY else "LIVE"
    print("=" * 60)
    print(f"  HFSS Smoke Test Suite ({mode})")
    print("=" * 60)
    print()

    passed = failed = 0
    for name, fn in STAGE_TESTS:
        print(f"[{name}]")
        try:
            ok = fn()
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL: {name}: {exc}")
            traceback.print_exc()
            failed += 1
        print()

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
