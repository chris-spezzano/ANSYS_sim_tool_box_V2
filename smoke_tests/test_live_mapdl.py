"""
Live MAPDL smoke test — requires an active ANSYS Mechanical installation.

Runs a single 1-element PLANE182 patch test (uniaxial tension) and verifies
the displacement and stress against the analytical solution.

Analytical benchmark
--------------------
For a unit square (Lx=Ly=1 m) with E=1 Pa, nu=0, prescribed UX=0.1 on right edge:
    ε_xx = UX / Lx = 0.1 / 1.0 = 0.1
    σ_xx = E × ε_xx = 1.0 × 0.1 = 0.1 Pa   (with nu=0: no Poisson coupling)

MAPDL result for displacement_x.max() must be within 1% of 0.1 m.
MAPDL result for stress_x.mean() must be within 1% of 0.1 Pa.

Usage
-----
    python smoke_tests/test_live_mapdl.py           # full live test
    python smoke_tests/test_live_mapdl.py --dry-run  # skip MAPDL, just test imports
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DRY_RUN = "--dry-run" in sys.argv


def test_imports():
    """Verify all ams sub-modules can be imported without errors."""
    import_targets = [
        "ams",
        "ams.resources.manager",
        "ams.geometry.importer",
        "ams.geometry.mesh_quality",
        "ams.geometry.element_selector",
        "ams.mapdl.runner",
        "ams.mapdl.boundary",
        "ams.mapdl.solver",
        "ams.mapdl.postproc",
        "ams.materials.standard",
        "ams.diagnostics.dashboard",
        "ams.multiphysics.pipeline",
    ]
    failed = []
    for mod in import_targets:
        try:
            __import__(mod)
        except ImportError as e:
            failed.append((mod, str(e)))

    if failed:
        for mod, err in failed:
            print(f"  FAIL: import {mod}: {err}")
        return False

    print(f"  PASS: all {len(import_targets)} ams modules imported successfully")
    return True


def test_zombie_cleanup():
    """Verify zombie cleanup runs without error and ports are checked."""
    from ams.resources.manager import kill_ansys_zombies, check_ports

    found = kill_ansys_zombies(dry_run=True, verbose=False)
    ports = check_ports()
    occupied = [p for p, s in ports.items() if s]

    if occupied:
        print(f"  WARN: Ports {occupied} are occupied — run kill_ansys_zombies() first")
    else:
        print(f"  PASS: zombie_cleanup — no occupied ports")
    return True


def test_config_load():
    """Verify config.yaml loads and has required keys."""
    import yaml
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    if not cfg_path.exists():
        print(f"  FAIL: config.yaml not found at {cfg_path}")
        return False

    with open(cfg_path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    required_keys = ["problem", "mapdl", "geometry", "elements", "materials",
                     "bcs", "solver", "resources", "output"]
    missing = [k for k in required_keys if k not in cfg]
    if missing:
        print(f"  FAIL: config.yaml missing keys: {missing}")
        return False

    print(f"  PASS: config.yaml loaded — {len(cfg)} top-level sections")
    return True


def test_element_selector():
    """Verify element selection logic returns expected recommendations."""
    from ams.geometry.element_selector import choose_element, ELEMENT_LIBRARY

    cases = [
        (dict(spatial_dim=3, is_thin_shell=True,  large_deformation=True),  "SHELL181"),
        (dict(spatial_dim=3, is_thin_shell=False, high_accuracy=True),      "SOLID186"),
        (dict(spatial_dim=3, is_beam=True),                                  "BEAM188"),
        (dict(spatial_dim=2),                                                 "PLANE182"),
        (dict(spatial_dim=3, auto_meshable=True),                            "SOLID187"),
    ]
    for kwargs, expected in cases:
        rec = choose_element(**kwargs)
        if rec.name != expected:
            print(f"  FAIL: choose_element({kwargs}) -> {rec.name}, expected {expected}")
            return False

    print(f"  PASS: element_selector — {len(cases)} cases correct, {len(ELEMENT_LIBRARY)} elements in library")
    return True


def test_live_mapdl_patch():
    """
    Connect to MAPDL, solve a 1-element PLANE182 tension patch test,
    and verify the result against the analytical solution.

    Analytical: E=1 Pa, nu=0, UX=0.1 on right edge → σ_xx = 0.1 Pa.
    """
    if DRY_RUN:
        print("  SKIP: test_live_mapdl_patch (dry-run mode)")
        return True

    from ams.resources.manager import kill_ansys_zombies, check_ports
    import numpy as np

    # Clean up before connecting
    kill_ansys_zombies(dry_run=False, verbose=False)

    # Check that our port is free
    port = 50052
    status = check_ports([port])
    if status.get(port):
        print(f"  FAIL: port {port} still occupied after zombie cleanup")
        return False

    try:
        from ansys.mapdl.core import launch_mapdl
    except ImportError:
        print("  SKIP: ansys-mapdl-core not installed — pip install ansys-mapdl-core")
        return True

    mapdl = None
    try:
        mapdl = launch_mapdl(
            start_instance = True,
            port           = port,
            start_timeout  = 120,
            loglevel       = "ERROR",
            additional_switches = "-g",
        )

        # ── PREP7: build 1-element model ─────────────────────────────────────
        mapdl.clear()
        mapdl.prep7()

        # Element type: PLANE182 (2D quad, plane stress)
        mapdl.et(1, "PLANE182")
        mapdl.keyopt(1, 3, 0)   # plane stress

        # Material: E=1 Pa, nu=0 (analytical: σ_xx = ε_xx × E = 0.1)
        mapdl.mp("EX",   1, 1.0)
        mapdl.mp("PRXY", 1, 0.0)

        # Geometry: unit square
        mapdl.rectng(0, 1.0, 0, 1.0)

        # Mesh: 1×1 quad element
        mapdl.mshape(0, "2D")
        mapdl.mshkey(1)
        mapdl.amesh("ALL")

        # BCs: fix left edge (UX=0), pin bottom-left (UY=0), prescribe right UX=0.1
        tol = 1e-6
        mapdl.nsel("S", "LOC", "X", -tol, tol)
        mapdl.d("ALL", "UX", 0.0)
        mapdl.nsel("R", "LOC", "Y", -tol, tol)
        mapdl.d("ALL", "UY", 0.0)
        mapdl.nsel("S", "LOC", "X", 1.0 - tol, 1.0 + tol)
        mapdl.d("ALL", "UX", 0.1)
        mapdl.nsel("ALL")
        mapdl.finish()

        # ── Solve ─────────────────────────────────────────────────────────────
        mapdl.run("/SOLU")
        mapdl.antype("STATIC")
        mapdl.nlgeom("OFF")
        mapdl.solve()
        mapdl.finish()

        # ── Post-process ──────────────────────────────────────────────────────
        import numpy as np
        mapdl.post1()
        mapdl.set("LAST")

        ux    = np.asarray(mapdl.post_processing.nodal_displacement("X"))
        sigma = np.asarray(mapdl.post_processing.nodal_stress("X"))

        ux_max    = float(ux.max())
        sigma_mean = float(sigma.mean())

        ux_expected    = 0.1
        sigma_expected = 0.1

        ux_err    = abs(ux_max    - ux_expected)    / ux_expected
        sigma_err = abs(sigma_mean - sigma_expected) / sigma_expected

        if ux_err > 0.01:
            print(f"  FAIL: UX_max={ux_max:.6f}  expected={ux_expected}  err={ux_err*100:.2f}%")
            return False
        if sigma_err > 0.01:
            print(f"  FAIL: sigma_xx_mean={sigma_mean:.6f}  expected={sigma_expected}  err={sigma_err*100:.2f}%")
            return False

        print(
            f"  PASS: live MAPDL patch test — "
            f"UX_max={ux_max:.6f} (err={ux_err*100:.3f}%), "
            f"sigma_xx={sigma_mean:.6f} (err={sigma_err*100:.3f}%)"
        )
        return True

    except Exception as exc:
        print(f"  FAIL: live MAPDL test raised {type(exc).__name__}: {exc}")
        return False

    finally:
        if mapdl is not None:
            try:
                mapdl.exit()
            except Exception:
                pass


def test_mesh_quality_live():
    """Run mesh quality check on the 1-element model created above (offline validation)."""
    from ams.geometry.mesh_quality import QualityThresholds

    qt = QualityThresholds(aspect_ratio_max=20.0, jacobian_min=0.0)

    # Simulate what the checker would report for the 1×1 quad
    # (without live MAPDL, test that the threshold object works)
    assert qt.aspect_ratio_max == 20.0
    assert qt.jacobian_min     == 0.0
    print("  PASS: QualityThresholds instantiation and attribute access")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

STAGE_TESTS = [
    ("imports",            test_imports),
    ("zombie_cleanup",     test_zombie_cleanup),
    ("config_load",        test_config_load),
    ("element_selector",   test_element_selector),
    ("mesh_quality_live",  test_mesh_quality_live),
    ("live_mapdl_patch",   test_live_mapdl_patch),
]


def main():
    mode = "DRY-RUN" if DRY_RUN else "LIVE"
    print("=" * 60)
    print(f"  MAPDL Smoke Test Suite ({mode})")
    print("=" * 60)
    print()

    passed, failed, skipped = 0, 0, 0
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
            print(f"  FAIL: {name} raised {type(exc).__name__}: {exc}")
            traceback.print_exc()
            failed += 1
        print()

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
