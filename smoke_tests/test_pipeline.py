"""Smoke test: multi-physics pipeline (offline — no MAPDL/HFSS needed)."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_pipeline_run():
    from ams.multiphysics.pipeline import SimulationPipeline, PipelineStage

    def stage_a(cfg, **kw):
        return {"value_a": 42, "array_a": [1, 2, 3]}

    def stage_b(cfg, value_a=None, **kw):
        assert value_a == 42, f"Expected 42, got {value_a}"
        return {"value_b": value_a * 2}

    pipeline = SimulationPipeline(
        stages=[
            PipelineStage("stage_a", run_fn=stage_a, config={}),
            PipelineStage("stage_b", run_fn=stage_b, config={},
                           input_map={"stage_a.value_a": "value_a"}),
        ],
        global_cfg={"problem": {"name": "test"}},
        output_dir="outputs/smoke_test",
    )
    results = pipeline.run()

    assert results["stage_a"]["value_a"] == 42
    assert results["stage_b"]["value_b"] == 84
    print(f"  PASS: pipeline.run() -> context keys: {list(results.keys())}")


def test_pipeline_sweep():
    from ams.multiphysics.pipeline import SimulationPipeline, PipelineStage

    values = []
    def stage_sweep(cfg, **kw):
        values.append(cfg.get("sweep_param", 0))
        return {"out": cfg.get("sweep_param", 0) * 2}

    pipeline = SimulationPipeline(
        stages=[PipelineStage("sweep", run_fn=stage_sweep, config={})],
        global_cfg={"problem": {"name": "sweep_test"}},
        output_dir="outputs/smoke_sweep",
    )
    param_sets = [{"sweep_param": v} for v in [1, 2, 3, 4, 5]]
    all_results = pipeline.sweep(param_sets)

    assert len(all_results) == 5
    assert all_results[2]["sweep"]["out"] == 6   # 3 * 2
    print(f"  PASS: pipeline.sweep({len(param_sets)} runs) -> {len(all_results)} results")


def test_deep_merge():
    from ams.multiphysics.pipeline import _deep_merge

    base     = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    override = {"b": {"c": 99, "f": 100}, "g": 7}
    merged   = _deep_merge(base, override)

    assert merged["a"]       == 1
    assert merged["b"]["c"]  == 99    # overridden
    assert merged["b"]["d"]  == 3     # preserved
    assert merged["b"]["f"]  == 100   # new key
    assert merged["g"]       == 7     # new top-level
    assert base["b"]["c"]    == 2     # original untouched

    print("  PASS: _deep_merge() — nested merge with original untouched")


def test_material_models():
    from ams.materials.standard import assign_elastic, assign_bilinear_plastic

    # Test the functions don't crash with a mock mapdl object
    class MockMapdl:
        def prep7(self): pass
        def mp(self, *a): pass
        def tb(self, *a): pass
        def tbdata(self, *a): pass
        def finish(self): pass

    mapdl = MockMapdl()
    assign_elastic(mapdl, 1, 200e9, 0.30, 7850.0, "steel")
    assign_bilinear_plastic(mapdl, 2, 200e9, 0.30, 7850.0, 250e6, 2e9, "steel_plastic")
    print("  PASS: assign_elastic(), assign_bilinear_plastic() with mock MAPDL")


if __name__ == "__main__":
    print("=" * 50)
    print("Pipeline & Material Smoke Tests")
    print("=" * 50)
    tests = [test_pipeline_run, test_pipeline_sweep, test_deep_merge, test_material_models]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAIL: {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
