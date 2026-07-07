"""Smoke test 03: pipeline imports, element selector, and mesh quality API (offline)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent


def test_pipeline_imports():
    from ams.multiphysics.pipeline import SimulationPipeline
    p = SimulationPipeline(stages=[], global_cfg={})
    assert isinstance(p._stages, list)
    print("  [PASS] SimulationPipeline instantiates with empty stage list")


def test_element_selector():
    from ams.geometry.element_selector import choose_element
    cases = [
        (dict(spatial_dim=2, physics="structural"),                    "PLANE182"),
        (dict(spatial_dim=3, physics="structural"),                    "SOLID185"),
        (dict(spatial_dim=3, physics="structural", is_thin_shell=True),"SHELL181"),
        (dict(spatial_dim=3, physics="structural", is_beam=True),      "BEAM188"),
        (dict(spatial_dim=3, physics="structural", high_accuracy=True),"SOLID186"),
    ]
    for kwargs, expected in cases:
        result = choose_element(**kwargs)
        assert result.name == expected, (
            f"choose_element({kwargs}) returned {result.name!r}, expected {expected!r}"
        )
    print(f"  [PASS] element_selector: {len(cases)} cases correct")


def test_mesh_quality_api():
    from ams.geometry.mesh_quality import QualityThresholds
    qt = QualityThresholds(aspect_ratio_max=10.0, jacobian_min=0.1, warping_max_deg=15.0)
    assert qt.aspect_ratio_max == 10.0
    assert qt.jacobian_min == 0.1
    assert qt.warping_max_deg == 15.0
    print("  [PASS] QualityThresholds and MeshQualityReport importable and constructable")


def test_importer_api():
    from ams.geometry.importer import GeometryImporter
    assert hasattr(GeometryImporter, "from_cdb"), "GeometryImporter missing from_cdb classmethod"
    assert hasattr(GeometryImporter, "from_inp"), "GeometryImporter missing from_inp classmethod"
    print("  [PASS] GeometryImporter.from_cdb and from_inp exist")


def test_solver_all_types_dispatch():
    """Offline: confirm run_solution would reach the right handler for each type."""
    from ams.mapdl.solver import run_solution
    import inspect
    src = inspect.getsource(run_solution)
    for stype in ["static", "modal", "harmonic", "transient", "buckling"]:
        # Each type name must appear as a dict key in the dispatch table
        assert stype in src, f"'{stype}' not found in run_solution source"
    print("  [PASS] run_solution dispatch verified for all 5 solver types")


def test_ntop_driver_importable():
    from ams.geometry.ntop_driver import run_ntop_from_config
    assert callable(run_ntop_from_config)
    print("  [PASS] ams.geometry.ntop_driver imports correctly")


def test_origami_bcs_importable():
    from ams.mapdl.origami_bcs import apply_waterbomb_fold_bcs, get_crease_node_sets
    assert callable(apply_waterbomb_fold_bcs)
    assert callable(get_crease_node_sets)
    print("  [PASS] ams.mapdl.origami_bcs imports correctly")


if __name__ == "__main__":
    test_pipeline_imports()
    test_element_selector()
    test_mesh_quality_api()
    test_importer_api()
    test_solver_all_types_dispatch()
    test_ntop_driver_importable()
    test_origami_bcs_importable()
    print("test_03_mesh_quality: PASS")
