"""Smoke test 02: config validation, solver strategy, and mesh quality thresholds."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

ROOT = Path(__file__).parent.parent


def test_config_solver_section():
    p = ROOT / "config.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    solver = cfg.get("solver", {})
    assert "type" in solver, "solver.type missing from config.yaml"
    assert solver["type"] in {"static", "modal", "harmonic", "transient", "buckling"}, (
        f"solver.type {solver['type']!r} is not a recognised solver type"
    )
    print(f"  [PASS] config.yaml solver section: type={solver['type']!r}")


def test_solver_strategy_from_config():
    from ams.mapdl.solver import SolverStrategy
    p = ROOT / "config.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    s = SolverStrategy.from_config(cfg)
    assert s.type in {"static", "modal", "harmonic", "transient", "buckling"}
    assert s.nsubsteps_initial >= 1
    assert 0.0 < s.cnvtol_force < 1.0
    print(f"  [PASS] SolverStrategy.from_config: type={s.type!r}, "
          f"nsubst_init={s.nsubsteps_initial}, cnvtol_F={s.cnvtol_force}")


def test_all_solver_types_instantiate():
    from ams.mapdl.solver import SolverStrategy
    for stype in ["static", "modal", "harmonic", "transient", "buckling"]:
        s = SolverStrategy(type=stype)
        assert s.type == stype
    print("  [PASS] SolverStrategy instantiates for all 5 solver types")


def test_solver_dispatch_table():
    """Verify run_solution dispatch covers all 5 solver types (offline check)."""
    import inspect
    from ams.mapdl import solver as solver_mod
    src = inspect.getsource(solver_mod.run_solution)
    for stype in ["static", "modal", "harmonic", "transient", "buckling"]:
        assert f'"{stype}"' in src or f"'{stype}'" in src, (
            f"solver type '{stype}' missing from run_solution dispatch table"
        )
    print("  [PASS] run_solution dispatch covers: static, modal, harmonic, transient, buckling")


def test_materials_yaml():
    p = ROOT / "config" / "materials.yaml"
    assert p.exists(), f"config/materials.yaml not found at {p}"
    with open(p) as f:
        data = yaml.safe_load(f)
    assert data, "materials.yaml is empty"
    print("  [PASS] config/materials.yaml exists and non-empty")


def test_quality_thresholds():
    from ams.geometry.mesh_quality import QualityThresholds
    p = ROOT / "config.yaml"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    thresholds = cfg.get("mesh", {}).get("quality_thresholds", {})
    qt = QualityThresholds(
        aspect_ratio_max=thresholds.get("aspect_ratio_max", 20.0),
        jacobian_min=thresholds.get("jacobian_min", 0.0),
        warping_max_deg=thresholds.get("warping_max_deg", 30.0),
    )
    assert qt.aspect_ratio_max > 0
    assert qt.warping_max_deg > 0
    print(f"  [PASS] QualityThresholds: AR_max={qt.aspect_ratio_max}, "
          f"warp_max={qt.warping_max_deg}°")


if __name__ == "__main__":
    test_config_solver_section()
    test_solver_strategy_from_config()
    test_all_solver_types_instantiate()
    test_solver_dispatch_table()
    test_materials_yaml()
    test_quality_thresholds()
    print("test_02_geometry: PASS")
