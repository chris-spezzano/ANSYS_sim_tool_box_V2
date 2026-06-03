"""Page 3 — Geometry: import, mesh quality check, and element type selection."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="Geometry", layout="wide")
st.title("Step 3 · Geometry & Mesh")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh: return yaml.safe_load(fh)
    return {}

def _save_cfg(cfg):
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

cfg = _load_cfg()
geom_cfg = cfg.setdefault("geometry", {})
mesh_cfg = cfg.setdefault("mesh", {})
elem_cfg = cfg.setdefault("elements", {})

# ── Element type selection ─────────────────────────────────────────────────────
st.subheader("Element Type")
from ams.geometry.element_selector import ELEMENT_LIBRARY, choose_element

element_names = list(ELEMENT_LIBRARY.keys())
selected_elem = st.selectbox(
    "Choose element type",
    element_names,
    index=element_names.index(elem_cfg.get("type", "SOLID186")),
    help=(
        "Not sure which to use? Use the guided selector below.\n"
        "See notebooks/03_geometry_import_and_mesh_quality.ipynb "
        "for full element theory."
    ),
)
elem_cfg["type"] = selected_elem
info = ELEMENT_LIBRARY.get(selected_elem)
if info:
    st.info(
        f"**{info.name}** — {info.spatial_dim}D, {info.n_nodes} nodes, "
        f"{info.integration} integration, large deformation: {'yes' if info.large_deform else 'no'}\n\n"
        f"**Best for:** {'; '.join(info.best_for[:2])}\n\n"
        f"**Avoid for:** {'; '.join(info.avoid_for[:1]) if info.avoid_for else 'N/A'}"
    )

st.markdown("---")

# ── Guided selector ────────────────────────────────────────────────────────────
with st.expander("Guided Element Selector"):
    s1, s2 = st.columns(2)
    with s1:
        dim         = st.radio("Spatial dimension", [2, 3], index=1)
        thin_shell  = st.checkbox("Thin shell / sheet structure")
        beam        = st.checkbox("Slender beam / frame")
    with s2:
        large_def   = st.checkbox("Large deformation (> 5% strain)", value=True)
        high_acc    = st.checkbox("High accuracy (quadratic elements)")
        auto_mesh   = st.checkbox("Complex CAD (auto-meshed tetrahedral)")

    if st.button("Recommend element type"):
        rec = choose_element(
            spatial_dim       = dim,
            is_thin_shell     = thin_shell,
            is_beam           = beam,
            large_deformation = large_def,
            high_accuracy     = high_acc,
            auto_meshable     = auto_mesh,
        )
        st.success(f"**Recommended: {rec.name}** — {rec.best_for[0]}")
        elem_cfg["type"] = rec.name

st.markdown("---")

# ── KEYOPT settings ────────────────────────────────────────────────────────────
st.subheader("Element Options (KEYOPT)")
ko = cfg.setdefault("elements", {}).setdefault("keyopt", {})
if selected_elem in ("PLANE182", "SOLID185"):
    ko["k2"] = st.selectbox(
        "KEYOPT(2) — Integration",
        [0, 1],
        index=int(ko.get("k2", 0)),
        format_func=lambda x: "0 = Full integration (recommended)" if x == 0
                               else "1 = Reduced integration (faster, hourglass risk)",
    )
if selected_elem == "PLANE182":
    ko["k3"] = st.selectbox(
        "KEYOPT(3) — Analysis type",
        [0, 1, 2],
        index=int(ko.get("k3", 0)),
        format_func=lambda x: {
            0: "0 = Plane stress", 1: "1 = Plane strain", 2: "2 = Axisymmetric"
        }[x],
    )

st.markdown("---")

# ── Parametric geometry (when source == parametric) ───────────────────────────
if geom_cfg.get("source", "parametric") == "parametric":
    st.subheader("Parametric Plate-With-Hole Geometry")
    plate = geom_cfg.setdefault("plate", {})
    c1, c2, c3 = st.columns(3)
    with c1:
        plate["width_m"]  = st.number_input("Width (m)",       value=float(plate.get("width_m",  0.10)), format="%.4f")
        plate["height_m"] = st.number_input("Height (m)",      value=float(plate.get("height_m", 0.10)), format="%.4f")
    with c2:
        plate["depth_m"]  = st.number_input("Depth/thickness (m)", value=float(plate.get("depth_m", 0.005)), format="%.4f")
    with c3:
        plate["hole_radius_m"] = st.number_input("Hole radius (m)",  value=float(plate.get("hole_radius_m", 0.010)), format="%.4f")

    w = plate["width_m"]; h = plate["height_m"]; r = plate["hole_radius_m"]
    Kt_approx = 3.0 + 3.13 * (r / (w/2))**2   # Pilkey §4.3.2 approximation
    st.info(
        f"Stress concentration factor (Pilkey): **Kt ≈ {Kt_approx:.2f}**\n\n"
        f"Predicted peak stress ≈ Kt × σ_far (verify with FEA)"
    )

# ── Mesh quality thresholds ────────────────────────────────────────────────────
st.subheader("Mesh Quality Thresholds")
qt = mesh_cfg.setdefault("quality_thresholds", {})
c1, c2, c3 = st.columns(3)
with c1:
    qt["aspect_ratio_max"]  = st.number_input("Max aspect ratio",   value=float(qt.get("aspect_ratio_max",  20.0)))
with c2:
    qt["jacobian_min"]      = st.number_input("Min Jacobian",       value=float(qt.get("jacobian_min",  0.0)), format="%.3f")
with c3:
    qt["warping_max_deg"]   = st.number_input("Max warp angle (°)", value=float(qt.get("warping_max_deg", 30.0)))

st.caption(
    "The solver is blocked if any critical check (Jacobian < 0, aspect ratio > limit) fails. "
    "See notebooks/03_geometry_import_and_mesh_quality.ipynb for theory."
)

# ── Save ───────────────────────────────────────────────────────────────────────
if st.button("Save Configuration", type="primary"):
    _save_cfg(cfg)
    st.success("Saved")
    st.session_state["cfg"] = cfg
