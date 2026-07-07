"""Smoke test 01: verify Python environment and core toolbox file presence."""

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

ROOT = Path(__file__).parent.parent


def test_ams_imports():
    required = [
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
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError as e:
            failed.append(f"{mod}: {e}")
    assert not failed, "Import failures:\n" + "\n".join(failed)
    print(f"  [PASS] All {len(required)} ams modules importable")


def test_third_party_imports():
    required = ["numpy", "matplotlib", "yaml", "meshio"]
    optional = ["pyvista", "pyaedt"]
    failed = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except ImportError as e:
            failed.append(f"{mod}: {e}")
    assert not failed, "Required dependency failures:\n" + "\n".join(failed)

    missing_opt = []
    for mod in optional:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing_opt.append(mod)
    if missing_opt:
        print(f"  [WARN] Optional packages not installed: {missing_opt}")
    print(f"  [PASS] All {len(required)} required dependencies importable")


def test_config_yaml():
    p = ROOT / "config.yaml"
    assert p.exists(), f"config.yaml not found at {p}"
    with open(p) as f:
        cfg = yaml.safe_load(f)
    required_keys = ["problem", "mapdl", "geometry", "mesh", "materials", "solver"]
    missing = [k for k in required_keys if k not in cfg]
    assert not missing, f"config.yaml missing top-level keys: {missing}"
    print(f"  [PASS] config.yaml has {len(cfg)} top-level sections (required all present)")


def test_simulation_mesh_exists():
    p = ROOT / "simulation_meshes" / "test_ansys.cdb"
    assert p.exists(), f"test_ansys.cdb not found at {p}"
    assert p.stat().st_size > 0, "test_ansys.cdb is empty"
    print(f"  [PASS] simulation_meshes/test_ansys.cdb exists ({p.stat().st_size // 1024} KB)")


def test_mapdl_binary():
    candidates = []
    for ver in ["252", "251", "242", "241"]:
        for drive in ["D:", "C:"]:
            p = rf"{drive}\ANSYS Inc\v{ver}\ansys\bin\winx64\ansys{ver}.exe"
            candidates.append(p)
            if os.path.exists(p):
                print(f"  [PASS] MAPDL binary found: {p}")
                return
    print("  [WARN] MAPDL binary not found in standard paths — manual path needed")
    # Not a hard failure: CI environments may not have ANSYS installed


if __name__ == "__main__":
    test_ams_imports()
    test_third_party_imports()
    test_config_yaml()
    test_simulation_mesh_exists()
    test_mapdl_binary()
    print("test_01_environment: PASS")
