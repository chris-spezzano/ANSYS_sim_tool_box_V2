"""Page 1 — I/O Paths: configure input/output directories."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="I/O Paths", layout="wide")
st.title("Step 1 · Input / Output Paths")
st.markdown("""
Configure where to find your geometry inputs and where to write results.
Every subsequent stage reads from and writes to these directories.
""")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    return {}

def _save_cfg(cfg):
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

cfg = _load_cfg()

# ── Problem metadata ───────────────────────────────────────────────────────────
st.subheader("Problem Description")
prob = cfg.setdefault("problem", {})

c1, c2 = st.columns(2)
with c1:
    prob["name"] = st.text_input(
        "Run name",
        value=prob.get("name", "my_simulation"),
        help="Human-readable label — used in output folder names and plot titles.",
    )
with c2:
    prob["physics"] = st.selectbox(
        "Physics type",
        ["structural", "thermal", "harmonic", "coupled"],
        index=["structural", "thermal", "harmonic", "coupled"].index(
            prob.get("physics", "structural")
        ),
        help="Governs which solver modules are activated.",
    )

# ── Geometry source ────────────────────────────────────────────────────────────
st.subheader("Geometry Source")
geom = cfg.setdefault("geometry", {})

source = st.selectbox(
    "Geometry source",
    ["parametric", "cdb", "stl", "step"],
    index=["parametric", "cdb", "stl", "step"].index(
        geom.get("source", "parametric")
    ),
    help=(
        "**parametric**: build geometry directly in MAPDL (no file needed)\n\n"
        "**cdb**: import mesh from nTopology or other FEA pre-processor\n\n"
        "**stl**: import surface mesh (limited — prefer CDB for structural)\n\n"
        "**step**: import CAD solid and mesh in MAPDL"
    ),
)
geom["source"] = source

if source == "cdb":
    geom["cdb_path"] = st.text_input(
        "CDB file path",
        value=geom.get("cdb_path") or "",
        placeholder="D:/Projects/geometry/origami_mesh.cdb",
        help="Absolute path to the .cdb file exported from nTopology.",
    )
    if geom.get("cdb_path"):
        if Path(geom["cdb_path"]).exists():
            st.success(f"File found: {Path(geom['cdb_path']).name}")
        else:
            st.error("File not found — check the path.")

elif source == "stl":
    geom["stl_path"] = st.text_input(
        "STL file path",
        value=geom.get("stl_path") or "",
        placeholder="D:/Projects/geometry/origami_mesh.stl",
    )

elif source == "parametric":
    st.info(
        "Parametric geometry is configured in Step 3 (Geometry). "
        "No file input required."
    )

# ── Output directories ─────────────────────────────────────────────────────────
st.subheader("Output Directory")
out = cfg.setdefault("output", {})

out_dir = st.text_input(
    "Output root directory",
    value=out.get("dir", "outputs"),
    help=(
        "All simulation results, plots, and CSVs will be written here.\n"
        "Sub-directories are created per run: outputs/{run_name}/..."
    ),
)
out["dir"] = out_dir

col1, col2, col3 = st.columns(3)
with col1:
    out["export_csv"]  = st.checkbox("Export CSV",  value=out.get("export_csv",  True))
with col2:
    out["export_vtk"]  = st.checkbox("Export VTK",  value=out.get("export_vtk",  True))
with col3:
    out["save_screenshots"] = st.checkbox("Screenshots", value=out.get("save_screenshots", True))

if st.button("Create output directory"):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    st.success(f"Created: {Path(out_dir).resolve()}")

# ── MAPDL working directory ────────────────────────────────────────────────────
st.subheader("MAPDL Working Directory")
mapdl = cfg.setdefault("mapdl", {})
run_loc = st.text_input(
    "MAPDL run location (optional)",
    value=mapdl.get("run_location") or "",
    placeholder="Leave blank for system temp dir",
    help=(
        "MAPDL writes scratch files here during the solve.\n"
        "Set this to a fast local SSD if the default temp dir is slow.\n"
        "Leave blank to use the OS temp directory."
    ),
)
mapdl["run_location"] = run_loc or None

# ── Save ───────────────────────────────────────────────────────────────────────
if st.button("Save Configuration", type="primary"):
    _save_cfg(cfg)
    st.success("Configuration saved to config.yaml")
    st.session_state["cfg"] = cfg
