"""
Smoke test orchestrator — runs all test stages in order and reports pass/fail.

Usage
-----
    python smoke_tests/run_all.py                # offline tests only
    python smoke_tests/run_all.py --live         # include live MAPDL test
    python smoke_tests/run_all.py --live --hfss  # include live MAPDL + HFSS
    python smoke_tests/run_all.py --help

Stage ordering
--------------
Offline stages (no ANSYS needed) run first.  Live stages are gated: if
the offline stages fail the live stages are skipped.  This prevents wasting
time trying to connect to MAPDL when there's a basic import error.

Exit code: 0 = all run stages passed, 1 = one or more failures.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
SMOKE = Path(__file__).parent

OFFLINE_TESTS = [
    (SMOKE / "test_resources.py",   "Resources (offline)"),
    (SMOKE / "test_mesh_quality.py","Mesh Quality (offline)"),
    (SMOKE / "test_pipeline.py",    "Pipeline & Materials (offline)"),
]

LIVE_MAPDL_TEST = (SMOKE / "test_live_mapdl.py", "Live MAPDL patch test")
LIVE_HFSS_TEST  = (SMOKE / "test_live_hfss.py",  "Live HFSS smoke test")


def _run(script: Path, label: str, extra_args: list[str] | None = None) -> bool:
    """Run a smoke test script, stream its output, return True if it passed."""
    args = [sys.executable, str(script)] + (extra_args or [])
    print(f"\n{'=' * 60}")
    print(f"  Running: {label}")
    print(f"{'=' * 60}")
    t0 = time.time()
    result = subprocess.run(args, cwd=str(ROOT))
    elapsed = time.time() - t0
    passed  = result.returncode == 0
    icon    = "PASS" if passed else "FAIL"
    print(f"  [{icon}]  {label}  ({elapsed:.1f} s)")
    return passed


def main():
    run_live      = "--live" in sys.argv
    run_hfss      = "--hfss" in sys.argv and run_live
    dry_run_live  = not run_live   # pass --dry-run to live tests when not in live mode

    print("=" * 60)
    print("  ANSYS Simulation Toolbox — Full Smoke Test Suite")
    print("=" * 60)
    print(f"  Mode: {'LIVE (MAPDL)' if run_live else 'OFFLINE'}{'+ HFSS' if run_hfss else ''}")
    print()

    results: list[tuple[str, bool]] = []

    # ── Offline tests ─────────────────────────────────────────────────────────
    print("OFFLINE TESTS (no ANSYS required)")
    offline_all_pass = True
    for script, label in OFFLINE_TESTS:
        ok = _run(script, label)
        results.append((label, ok))
        if not ok:
            offline_all_pass = False

    # ── Live MAPDL test ───────────────────────────────────────────────────────
    script, label = LIVE_MAPDL_TEST
    if not offline_all_pass:
        print(f"\n  SKIP: {label} — offline tests failed, fix those first")
        results.append((label, False))
    else:
        extra = [] if run_live else ["--dry-run"]
        ok = _run(script, label, extra_args=extra)
        results.append((label, ok))

    # ── Live HFSS test ────────────────────────────────────────────────────────
    script, label = LIVE_HFSS_TEST
    if not run_hfss:
        extra = ["--dry-run"]
    elif not offline_all_pass:
        print(f"\n  SKIP: {label} — offline tests failed")
        results.append((label, False))
        extra = None
    else:
        extra = []
    if extra is not None:
        ok = _run(script, label, extra_args=extra)
        results.append((label, ok))

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    total  = len(results)
    passed = sum(1 for _, ok in results if ok)
    for label, ok in results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}]  {label}")

    print()
    print(f"  {passed}/{total} test suites passed")

    if passed < total:
        print()
        print("  NEXT STEPS:")
        for label, ok in results:
            if not ok:
                print(f"    - Re-run: python smoke_tests/{_script_name(label)}")
    print("=" * 60)
    sys.exit(0 if passed == total else 1)


def _script_name(label: str) -> str:
    mapping = {
        "Resources (offline)":          "test_resources.py",
        "Mesh Quality (offline)":        "test_mesh_quality.py",
        "Pipeline & Materials (offline)":"test_pipeline.py",
        "Live MAPDL patch test":         "test_live_mapdl.py",
        "Live HFSS smoke test":          "test_live_hfss.py",
    }
    return mapping.get(label, label)


if __name__ == "__main__":
    main()
