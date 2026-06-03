"""
Multi-Physics Pipeline — chain simulations and schedule experiments.

A SimulationPipeline is a directed sequence of PipelineStages, where the
output of each stage can feed as input to the next.  This supports:

  1. Sequential multi-physics (structural → EM → thermal → structural)
  2. Parametric sweeps  (run N variants with a shared pipeline definition)
  3. Staged restart     (checkpoint / resume from a failed stage)
  4. Scheduled runs     (fire-and-forget with output directory management)

Architecture
------------
PipelineStage:
    name:       str
    run_fn:     Callable[..., dict]   — executes the simulation
    input_map:  dict[str, str]        — maps prior stage output keys → input keys
    config:     dict                  — stage-specific config overrides

SimulationPipeline:
    stages:     list[PipelineStage]
    context:    dict                  — accumulated outputs from all stages
    run()       → dict                — execute all stages in order
    sweep()     → list[dict]          — run the pipeline for each param set

Typical origami workflow
------------------------
pipeline = SimulationPipeline([
    PipelineStage("geometry",   run_fn=run_ntop_export,      config=ntop_cfg),
    PipelineStage("structural", run_fn=run_mapdl_folding,   config=mapdl_cfg,
                  input_map={"geometry.cdb_path": "cdb_path"}),
    PipelineStage("em_shielding", run_fn=run_hfss_analysis, config=hfss_cfg,
                  input_map={"structural.stl_path": "stl_path"}),
    PipelineStage("postprocess", run_fn=aggregate_results,  config={}),
])
results = pipeline.run()

Data flow
---------
Each stage's run_fn receives:
  - Its stage config (with any overrides applied)
  - Values from prior stages (resolved via input_map)
  - The full pipeline context dict

And returns a flat dict of outputs.  These are stored in context under
the stage name: context[stage.name] = stage_outputs.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PipelineStage
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineStage:
    """A single stage in a multi-physics pipeline.

    Attributes
    ----------
    name : str
        Unique identifier for this stage.  Used as the context key.
    run_fn : Callable
        Function to execute.  Signature: run_fn(config, **kwargs) -> dict.
    config : dict
        Stage-specific configuration.  Merged with global config.
    input_map : dict[str, str]
        Maps context keys from prior stages to kwarg names for run_fn.
        Format: {"prior_stage.output_key": "kwarg_name"}
    skip_if : Callable[[dict], bool] | None
        If set, skip this stage when skip_if(context) returns True.
        Useful for skipping geometry export if the CDB already exists.
    checkpoint_key : str | None
        If set, save the stage output to a JSON checkpoint file.
        The pipeline will reload this on resume instead of re-running.
    """
    name:          str
    run_fn:        Callable[..., dict]
    config:        dict = field(default_factory=dict)
    input_map:     dict[str, str] = field(default_factory=dict)
    skip_if:       Callable[[dict], bool] | None = None
    checkpoint_key: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# SimulationPipeline
# ─────────────────────────────────────────────────────────────────────────────

class SimulationPipeline:
    """Orchestrate a sequence of simulation stages.

    Parameters
    ----------
    stages : list[PipelineStage]
        Ordered list of stages to execute.
    global_cfg : dict
        Shared config merged under each stage's local config.
    output_dir : str | Path
        Root directory for all stage outputs.
    resume_from : str | None
        Stage name to resume from (skipping all prior stages that have
        a checkpoint file on disk).

    Example
    -------
    >>> from ams.multiphysics.pipeline import SimulationPipeline, PipelineStage
    >>> pipeline = SimulationPipeline(
    ...     stages     = [stage1, stage2, stage3],
    ...     global_cfg = load_config("config.yaml"),
    ...     output_dir = "outputs/run_001",
    ... )
    >>> results = pipeline.run()
    >>> print(results["em_shielding"]["SE_dB"].mean())
    """

    def __init__(
        self,
        stages:       list[PipelineStage],
        global_cfg:   dict = None,
        output_dir:   str | Path = "outputs",
        resume_from:  str | None = None,
    ):
        self._stages      = stages
        self._global_cfg  = global_cfg or {}
        self._output_dir  = Path(output_dir)
        self._resume_from = resume_from
        self._context:    dict[str, dict] = {}
        self._timings:    dict[str, float] = {}

        self._output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict[str, dict]:
        """Execute all pipeline stages in order.

        Returns
        -------
        dict
            The full pipeline context: {stage_name: {output_key: value, ...}}
        """
        log.info("=== Pipeline START (%d stages) ===", len(self._stages))
        self._load_checkpoints()

        for stage in self._stages:
            if self._should_skip(stage):
                log.info("  [%s] SKIP — checkpoint exists or skip_if=True", stage.name)
                continue

            log.info("  [%s] START", stage.name)
            t0 = time.time()

            try:
                outputs = self._run_stage(stage)
                self._context[stage.name] = outputs
                self._timings[stage.name] = time.time() - t0

                if stage.checkpoint_key:
                    self._save_checkpoint(stage.name, outputs)

                log.info(
                    "  [%s] DONE (%.1f s) — outputs: %s",
                    stage.name, self._timings[stage.name], list(outputs.keys()),
                )

            except Exception as exc:
                log.error("  [%s] FAILED: %s", stage.name, exc)
                self._save_pipeline_state("FAILED", stage.name, str(exc))
                raise RuntimeError(
                    f"Pipeline stage '{stage.name}' failed: {exc}\n"
                    f"Fix the issue and restart with resume_from='{stage.name}'."
                ) from exc

        total = sum(self._timings.values())
        log.info("=== Pipeline COMPLETE (total %.1f s) ===", total)
        self._save_pipeline_state("COMPLETE")
        return self._context

    def sweep(
        self,
        param_sets: list[dict],
        stage_name: str | None = None,
    ) -> list[dict]:
        """Run the pipeline for each parameter set.

        Parameters
        ----------
        param_sets : list[dict]
            List of config override dicts.  Each dict is merged into
            the global config for that run.
        stage_name : str | None
            If set, only override the config of this specific stage.
            If None, overrides are applied globally.

        Returns
        -------
        list[dict]
            One context dict per parameter set.

        Example
        -------
        Run 5 simulations with different hole radii:
        >>> results = pipeline.sweep([
        ...     {"geometry.plate.hole_radius_m": 0.010},
        ...     {"geometry.plate.hole_radius_m": 0.015},
        ...     {"geometry.plate.hole_radius_m": 0.020},
        ... ])
        """
        all_results = []
        for i, params in enumerate(param_sets):
            log.info("Sweep %d/%d: %s", i+1, len(param_sets), params)

            # Create a new pipeline instance with modified config
            merged_cfg = _deep_merge(self._global_cfg, params)
            sub_pipeline = SimulationPipeline(
                stages     = self._stages,
                global_cfg = merged_cfg,
                output_dir = self._output_dir / f"sweep_{i:04d}",
            )
            result = sub_pipeline.run()
            all_results.append(result)

        return all_results

    def add_stage(self, stage: PipelineStage, after: str | None = None) -> None:
        """Add a stage to the pipeline, optionally after a named stage."""
        if after is None:
            self._stages.append(stage)
        else:
            idx = next((i for i, s in enumerate(self._stages) if s.name == after), None)
            if idx is None:
                raise ValueError(f"Stage '{after}' not found in pipeline")
            self._stages.insert(idx + 1, stage)

    def print_plan(self) -> None:
        """Print the pipeline stage plan."""
        print("\n" + "=" * 56)
        print("  Pipeline Plan")
        print("=" * 56)
        for i, stage in enumerate(self._stages):
            status = "CHECKPOINTED" if stage.name in self._context else "pending"
            print(f"  {i+1:2d}. [{status}] {stage.name}")
            if stage.input_map:
                for src, dst in stage.input_map.items():
                    print(f"           ← {src} → {dst}")
        print("=" * 56 + "\n")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_stage(self, stage: PipelineStage) -> dict:
        """Resolve inputs and call stage.run_fn."""
        merged_cfg = _deep_merge(self._global_cfg, stage.config)

        # Build kwargs from input_map
        kwargs: dict[str, Any] = {}
        for context_key, kwarg_name in stage.input_map.items():
            value = self._resolve_context_key(context_key)
            kwargs[kwarg_name] = value

        return stage.run_fn(merged_cfg, **kwargs)

    def _resolve_context_key(self, key: str) -> Any:
        """Resolve a dotted context key like 'stage_name.output_key'."""
        parts = key.split(".", 1)
        if len(parts) == 2:
            stage_name, output_key = parts
            stage_ctx = self._context.get(stage_name, {})
            if output_key not in stage_ctx:
                raise KeyError(
                    f"Context key '{key}' not found.  "
                    f"Available in '{stage_name}': {list(stage_ctx.keys())}"
                )
            return stage_ctx[output_key]
        return self._context.get(key)

    def _should_skip(self, stage: PipelineStage) -> bool:
        if stage.name in self._context:
            return True
        if stage.skip_if and stage.skip_if(self._context):
            return True
        return False

    def _save_checkpoint(self, stage_name: str, outputs: dict) -> None:
        """Save stage outputs to JSON checkpoint."""
        cp_path = self._output_dir / f"checkpoint_{stage_name}.json"
        # Serialise only JSON-serialisable keys (skip numpy arrays)
        safe = {}
        for k, v in outputs.items():
            try:
                json.dumps(v)
                safe[k] = v
            except (TypeError, ValueError):
                safe[k] = str(v)
        with open(cp_path, "w", encoding="utf-8") as fh:
            json.dump(safe, fh, indent=2)
        log.debug("Checkpoint saved → %s", cp_path)

    def _load_checkpoints(self) -> None:
        """Load any existing checkpoint files (for pipeline resume)."""
        for stage in self._stages:
            if not stage.checkpoint_key:
                continue
            cp_path = self._output_dir / f"checkpoint_{stage.name}.json"
            if cp_path.exists():
                with open(cp_path, encoding="utf-8") as fh:
                    self._context[stage.name] = json.load(fh)
                log.info("Loaded checkpoint for stage '%s'", stage.name)

    def _save_pipeline_state(
        self,
        status: str,
        failed_stage: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        """Write pipeline status to a JSON file for post-run inspection."""
        state = {
            "status":        status,
            "stages_done":   list(self._context.keys()),
            "timings_s":     self._timings,
            "failed_stage":  failed_stage,
            "error":         error_msg,
        }
        state_path = self._output_dir / "pipeline_state.json"
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Utility — deep merge two dicts
# ─────────────────────────────────────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into a copy of base."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pre-built stage factories for the standard origami workflow
# ─────────────────────────────────────────────────────────────────────────────

def make_mapdl_structural_stage(
    config_override: dict | None = None,
) -> PipelineStage:
    """Factory: MAPDL large-deformation structural stage."""
    from ..mapdl.runner import MAPDLRunner
    from ..mapdl.solver import run_solution, SolverStrategy
    from ..mapdl.postproc import extract_results, write_csv, save_animation
    from ..geometry.importer import GeometryImporter
    from ..geometry.mesh_quality import MeshQualityChecker
    from ..mapdl.boundary import apply_boundary_conditions
    from ..materials.standard import apply_materials

    def run_structural(cfg: dict, cdb_path: str | None = None) -> dict:
        runner = MAPDLRunner(cfg)
        mapdl  = runner.connect()
        try:
            mapdl.clear()
            mapdl.prep7()

            gi = GeometryImporter(mapdl)
            if cdb_path:
                gi.from_cdb(cdb_path)
            else:
                gi.build_plate_with_hole(**cfg.get("geometry", {}).get("plate", {}))

            apply_materials(mapdl, cfg)
            apply_boundary_conditions(mapdl, cfg.get("bcs", {}))

            checker = MeshQualityChecker(mapdl)
            report  = checker.check(raise_on_fail=True)

            strategy = SolverStrategy.from_config(cfg)
            run_solution(mapdl, strategy)

            out_dir  = cfg.get("output", {}).get("dir", "outputs")
            results  = extract_results(mapdl, ["displacement_norm", "von_mises"])
            write_csv(results, out_dir)

            # Export deformed geometry for HFSS
            stl_path = str(Path(out_dir) / "deformed_geometry.stl")
            gi.export_stl(stl_path)

            return {"stl_path": stl_path, "results": results, "mesh_report": report}
        finally:
            runner.disconnect()

    return PipelineStage(
        name      = "structural",
        run_fn    = run_structural,
        config    = config_override or {},
        checkpoint_key = "structural",
    )


def make_hfss_em_stage(
    config_override: dict | None = None,
) -> PipelineStage:
    """Factory: HFSS electromagnetic analysis stage."""
    from ..hfss.runner   import HFSSRunner
    from ..hfss.boundary import assign_finite_conductivity, assign_floquet_port
    from ..hfss.postproc import extract_s_parameters, write_s_parameters_csv, save_sparameter_plots

    def run_em(cfg: dict, stl_path: str | None = None) -> dict:
        runner = HFSSRunner(cfg)
        hfss   = runner.connect()
        try:
            hfss_cfg = cfg.get("hfss", {})
            out_dir  = Path(cfg.get("output", {}).get("dir", "outputs")) / "em"
            out_dir.mkdir(parents=True, exist_ok=True)

            # Import geometry
            if stl_path:
                hfss.modeler.import_3d_cad(
                    stl_path,
                    import_free_surfaces=True,
                    import_as_light_weight=False,
                )
                # Clean up non-manifold helper objects from STL import
                for obj_name in list(hfss.modeler.objects.keys()):
                    if obj_name.endswith("_Unnamed_6"):
                        hfss.modeler.delete(obj_name)

            # Assign EM BCs
            em_mats = hfss_cfg.get("materials_em", [])
            for mat in em_mats:
                if "conductivity_S_m" in mat:
                    for obj_name in hfss.modeler.objects:
                        assign_finite_conductivity(hfss, obj_name,
                                                   mat["conductivity_S_m"],
                                                   name=f"FiniteCond_{mat['name']}")

            # Solution setup
            setup_cfg = hfss_cfg.get("setup", {})
            setup = hfss.create_setup("Setup1")
            setup.props["MaximumPasses"]   = setup_cfg.get("adaptive_passes", 6)
            setup.props["MaxDeltaS"]       = setup_cfg.get("max_delta_s", 0.01)

            sweep = setup.add_sweep("Sweep1", sweeptype="Interpolating")
            sweep.props["RangeStart"] = f"{setup_cfg.get('freq_start_GHz', 1.0)}GHz"
            sweep.props["RangeEnd"]   = f"{setup_cfg.get('freq_stop_GHz', 20.0)}GHz"
            sweep.props["RangeCount"] = int(setup_cfg.get("n_freq_points", 200))

            # Solve
            hfss.analyze()

            # Extract results
            results = extract_s_parameters(hfss)
            csv_path = write_s_parameters_csv(results, out_dir)
            save_sparameter_plots(results, out_dir)

            return {"emi_results": results, "csv_path": str(csv_path)}
        finally:
            runner.disconnect()

    return PipelineStage(
        name      = "em_shielding",
        run_fn    = run_em,
        config    = config_override or {},
        input_map = {"structural.stl_path": "stl_path"},
        checkpoint_key = "em_shielding",
    )
