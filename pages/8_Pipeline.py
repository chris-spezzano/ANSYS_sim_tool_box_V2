"""Page 8 — Pipeline: chain experiments and schedule multi-physics workflows."""

import streamlit as st
import yaml, json
from pathlib import Path

st.set_page_config(page_title="Pipeline", layout="wide")
st.title("Step 8 · Multi-Physics Pipeline")
st.markdown("""
Chain simulation stages into automated workflows.  Configure a sequential
structural → EM pipeline, or sweep a parameter across multiple runs.

See **notebooks/08_multiphysics_pipeline.ipynb** for the full pipeline API.
""")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh: return yaml.safe_load(fh)
    return {}

def _save_cfg(cfg):
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

cfg = _load_cfg()

tab_plan, tab_sweep, tab_status = st.tabs(["Pipeline Plan", "Parametric Sweep", "Run Status"])

# ─────────────────────────────────────────────────────────────────────────────
with tab_plan:
    st.subheader("Workflow Stages")

    st.markdown("""
    The standard origami EMI pipeline chains four stages:

    ```
    nTopology (geometry)
        ↓  origami_mesh.cdb
    MAPDL structural (large-deformation folding)
        ↓  deformed_geometry.stl
    HFSS EM (periodic unit cell S-parameters)
        ↓  emi_results.csv
    Post-processing (aggregate + visualize)
    ```
    """)

    # Stage enable checkboxes
    st.markdown("**Enable / disable stages:**")
    c1, c2, c3, c4 = st.columns(4)
    with c1: run_ntop     = st.checkbox("nTopology geometry",  value=True)
    with c2: run_mapdl    = st.checkbox("MAPDL structural",    value=True)
    with c3: run_hfss     = st.checkbox("HFSS EM",             value=True)
    with c4: run_postproc = st.checkbox("Post-processing",     value=True)

    st.markdown("---")
    st.markdown("**Pipeline code preview** (copy to notebook):")

    code = """from ams.multiphysics.pipeline import (
    SimulationPipeline, make_mapdl_structural_stage, make_hfss_em_stage
)
from ams.config import load_config

cfg = load_config("config.yaml")

pipeline = SimulationPipeline(
    stages=[
"""
    if run_ntop:
        code += "        # Stage 1: nTopology geometry export (define your own run_fn)\n"
    if run_mapdl:
        code += "        make_mapdl_structural_stage(),\n"
    if run_hfss:
        code += "        make_hfss_em_stage(),\n"
    code += """    ],
    global_cfg = cfg,
    output_dir = "outputs",
)
results = pipeline.run()
"""
    st.code(code, language="python")

# ─────────────────────────────────────────────────────────────────────────────
with tab_sweep:
    st.subheader("Parametric Sweep")
    st.markdown("""
    Run the pipeline for multiple parameter values.  Results are stored in
    separate sub-directories: `outputs/sweep_0000/`, `outputs/sweep_0001/`, ...
    """)

    sweep_param = st.selectbox(
        "Parameter to sweep",
        [
            "geometry.plate.hole_radius_m",
            "bcs.loads[0].value_Pa",
            "materials[0].E_Pa",
            "solver.nsubst.max",
        ],
        help="Dot-separated path into the config dict.",
    )

    sweep_values_raw = st.text_area(
        "Values (one per line)",
        value="0.005\n0.010\n0.015\n0.020",
        help="One numeric value per line.",
    )
    try:
        sweep_values = [float(v.strip()) for v in sweep_values_raw.splitlines() if v.strip()]
        st.caption(f"{len(sweep_values)} sweep points")
    except ValueError:
        st.error("All values must be numeric")
        sweep_values = []

    if sweep_values:
        param_sets = [{sweep_param: v} for v in sweep_values]
        st.markdown("**Sweep code:**")
        st.code(f"""results = pipeline.sweep(
    param_sets={json.dumps(param_sets[:3], indent=4)}
    {"... # and more" if len(param_sets) > 3 else ""}
)""", language="python")

# ─────────────────────────────────────────────────────────────────────────────
with tab_status:
    st.subheader("Pipeline Run Status")
    out_dir = Path(cfg.get("output", {}).get("dir", "outputs"))
    state_file = out_dir / "pipeline_state.json"

    if st.button("Refresh"):
        st.rerun()

    if state_file.exists():
        with open(state_file, encoding="utf-8") as fh:
            state = json.load(fh)
        status = state.get("status", "?")
        icon   = {"COMPLETE": "✅", "FAILED": "❌"}.get(status, "⏳")
        st.metric("Status", f"{icon} {status}")
        st.json(state)
    else:
        st.info(f"No pipeline state found at `{state_file}`.")

    # Checkpoint browser
    st.subheader("Checkpoints")
    checkpoints = list(out_dir.glob("checkpoint_*.json"))
    if checkpoints:
        for cp in checkpoints:
            stage_name = cp.stem.replace("checkpoint_", "")
            with st.expander(f"Checkpoint: {stage_name}"):
                with open(cp, encoding="utf-8") as fh:
                    st.json(json.load(fh))
    else:
        st.info("No checkpoint files found.")
