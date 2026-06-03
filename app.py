"""ANSYS Simulation Toolbox — Streamlit Home Page.

Launch with:
    streamlit run app.py
"""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(
    page_title  = "ANSYS Sim Toolbox",
    page_icon   = "⚙️",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)


def _load_cfg() -> dict:
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    return {}


def _save_cfg(cfg: dict) -> None:
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)


# ── Session state init ────────────────────────────────────────────────────────
if "cfg" not in st.session_state:
    st.session_state["cfg"] = _load_cfg()

cfg = st.session_state["cfg"]

# ── Title & intro ─────────────────────────────────────────────────────────────
st.title("ANSYS Simulation Toolbox")
st.markdown("""
**A step-by-step guided workflow for ANSYS MAPDL (structural / thermal)
and AEDT HFSS (electromagnetic) simulations.**

Designed for engineers and researchers learning FEA/EM simulation.
Each stage is backed by a Jupyter notebook with full mathematical and
computational detail.
""")

# ── Workflow diagram ───────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Workflow Overview")
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.info("**1 · I/O Paths**\nConfigure input & output directories")
with col2:
    st.info("**2 · Resources**\nAllocate CPU/RAM\nKill zombie processes")
with col3:
    st.info("**3 · Geometry**\nImport mesh\nCheck quality\nChoose element type")
with col4:
    st.info("**4 · BCs**\nDisplacement, force\nPeriodic, symmetry\nEM boundaries")
with col5:
    st.info("**5 · Solver**\nNewton-Raphson\nConvergence settings")

col6, col7, col8, _ = st.columns(4)
with col6:
    st.success("**6 · Diagnostics**\nLive convergence\nPort health\nRST size")
with col7:
    st.success("**7 · Results**\nVisualize fields\nProbe points\nExport VTK/CSV")
with col8:
    st.success("**8 · Pipeline**\nChain experiments\nParametric sweep\nSchedule runs")

# ── Quick status panel ────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Current Configuration")

c1, c2, c3 = st.columns(3)
with c1:
    problem_name = cfg.get("problem", {}).get("name", "unnamed")
    physics      = cfg.get("problem", {}).get("physics", "structural")
    st.metric("Problem", problem_name)
    st.metric("Physics", physics)

with c2:
    mapdl_port = cfg.get("mapdl", {}).get("port", 50052)
    nproc      = cfg.get("resources", {}).get("max_nproc", 1)
    st.metric("MAPDL port", mapdl_port)
    st.metric("Max CPUs", nproc)

with c3:
    out_dir = cfg.get("output", {}).get("dir", "outputs")
    st.metric("Output directory", out_dir)

# ── Quick actions ────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Quick Actions")

col_a, col_b, col_c = st.columns(3)

with col_a:
    if st.button("Kill ANSYS Zombies", type="secondary"):
        try:
            from ams.resources.manager import kill_ansys_zombies
            killed = kill_ansys_zombies(dry_run=False, verbose=False)
            if killed:
                st.success(f"Killed {len(killed)} zombie process(es)")
            else:
                st.info("No zombie processes found")
        except Exception as e:
            st.error(f"Error: {e}")

with col_b:
    if st.button("Check Ports", type="secondary"):
        try:
            from ams.resources.manager import check_ports
            status = check_ports()
            occ = [p for p, s in status.items() if s]
            free = [p for p, s in status.items() if not s]
            st.success(f"Occupied: {occ or 'none'}  |  Free: {free[:5]}")
        except Exception as e:
            st.error(f"Error: {e}")

with col_c:
    if st.button("Resource Estimate", type="secondary"):
        try:
            from ams.resources.manager import ResourceManager
            rm  = ResourceManager()
            rec = rm.recommend()
            st.success(
                f"nproc={rec.nproc} | RAM={rec.ram_mb} MB | "
                f"port={rec.mapdl_port}"
            )
        except Exception as e:
            st.error(f"Error: {e}")

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "ANSYS Simulation Toolbox v1.0 · "
    "Navigate to each stage using the sidebar pages · "
    "See `notebooks/` for full mathematical detail"
)
