"""Page 4 — Boundary Conditions: kinematic and load BCs for MAPDL and HFSS."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="Boundary Conditions", layout="wide")
st.title("Step 4 · Boundary Conditions")
st.markdown("""
Define how the structure is supported (kinematic BCs) and how it is loaded
(Neumann BCs).  See **notebooks/04_boundary_conditions.ipynb** for the
full mathematical framework including weak-form derivations.
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
bcs = cfg.setdefault("bcs", {})
constraints = bcs.setdefault("constraints", [])
loads       = bcs.setdefault("loads",       [])

tab_struct, tab_em, tab_periodic = st.tabs([
    "Structural BCs", "EM Boundaries (HFSS)", "Periodic / Unit Cell"
])

# ─────────────────────────────────────────────────────────────────────────────
with tab_struct:
    st.subheader("Kinematic Constraints (Dirichlet)")
    st.markdown("""
    | Type | Equation | Typical use |
    |------|----------|-------------|
    | Fixed face | u = 0 on Γ_D | Clamped wall |
    | Displacement | u = ū on Γ_D | Prescribed motion |
    | Symmetry | u_n = 0 on Γ_sym | Half-model |
    | Periodic | u(x+L) = u(x) | Unit cell |
    """)

    if not constraints:
        st.info("No constraints defined yet.  Add one below.")

    for i, bc in enumerate(constraints):
        with st.expander(f"Constraint {i+1}: {bc.get('type','?')} on {bc.get('axis','?')}={bc.get('side','?')}"):
            bc["type"] = st.selectbox(f"Type##c{i}", ["displacement", "fixed", "symmetry"],
                                      index=["displacement","fixed","symmetry"].index(bc.get("type","fixed")),
                                      key=f"ctype_{i}")
            bc["axis"] = st.selectbox(f"Face axis##c{i}", ["X","Y","Z"],
                                      index=["X","Y","Z"].index(bc.get("axis","X")), key=f"caxis_{i}")
            bc["side"] = st.selectbox(f"Side##c{i}", ["min","max"],
                                      index=["min","max"].index(bc.get("side","min")), key=f"cside_{i}")
            if bc["type"] == "displacement":
                dof_opts = ["UX","UY","UZ","ALL","ROTX","ROTY","ROTZ"]
                bc["dofs"]  = st.multiselect(f"DOFs##c{i}", dof_opts,
                                              default=bc.get("dofs",["UX","UY","UZ"]), key=f"cdofs_{i}")
                bc["value"] = st.number_input(f"Value (m)##c{i}", value=float(bc.get("value",0.0)), key=f"cval_{i}")
            if st.button(f"Remove constraint {i+1}", key=f"crem_{i}"):
                constraints.pop(i); st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Add Fixed Face"):
            constraints.append({"type": "fixed", "axis": "X", "side": "min", "dofs": ["ALL"], "value": 0.0})
            st.rerun()
    with c2:
        if st.button("Add Displacement BC"):
            constraints.append({"type": "displacement", "axis": "X", "side": "max", "dofs": ["UX"], "value": 0.01})
            st.rerun()

    st.subheader("Loads (Neumann)")
    st.markdown("""
    | Type | Equation | Typical use |
    |------|----------|-------------|
    | Pressure | σ·n = -p on Γ_N | Tensile/compressive traction |
    | Gravity | ρg body force | Self-weight |
    | Force | F concentrated at node | Point load |
    """)

    for i, bc in enumerate(loads):
        with st.expander(f"Load {i+1}: {bc.get('type','?')}"):
            bc["type"] = st.selectbox(f"Type##l{i}", ["pressure","force","gravity"],
                                      index=["pressure","force","gravity"].index(bc.get("type","pressure")),
                                      key=f"ltype_{i}")
            if bc["type"] == "pressure":
                bc["axis"]     = st.selectbox(f"Axis##l{i}", ["X","Y","Z"],
                                               index=["X","Y","Z"].index(bc.get("axis","X")), key=f"laxis_{i}")
                bc["side"]     = st.selectbox(f"Side##l{i}", ["min","max"],
                                               index=["min","max"].index(bc.get("side","max")), key=f"lside_{i}")
                bc["value_Pa"] = st.number_input(f"Pressure (Pa)##l{i}", value=float(bc.get("value_Pa",-100e6)),
                                                  format="%.3e", key=f"lpval_{i}")
                st.caption("Negative = tensile (pulling away from face)")
            elif bc["type"] == "force":
                bc["node_id"]  = st.number_input(f"Node ID##l{i}", value=int(bc.get("node_id",1)), key=f"lnid_{i}")
                bc["dof"]      = st.selectbox(f"DOF##l{i}", ["FX","FY","FZ","MX","MY","MZ"],
                                               index=["FX","FY","FZ","MX","MY","MZ"].index(bc.get("dof","FY")),
                                               key=f"ldof_{i}")
                bc["value_N"]  = st.number_input(f"Value (N or N·m)##l{i}", value=float(bc.get("value_N",0.0)), key=f"lnval_{i}")
            if st.button(f"Remove load {i+1}", key=f"lrem_{i}"):
                loads.pop(i); st.rerun()

    if st.button("Add Pressure Load"):
        loads.append({"type": "pressure", "axis": "X", "side": "max", "value_Pa": -100e6})
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
with tab_em:
    st.subheader("HFSS Electromagnetic Boundaries")
    hfss = cfg.setdefault("hfss", {})
    hbc  = hfss.setdefault("boundaries", {})

    bc_type = st.selectbox(
        "Boundary type",
        ["floquet", "radiation"],
        index=["floquet","radiation"].index(hbc.get("type","floquet")),
        help=(
            "**floquet**: for periodic arrays (infinite lattice) — use with periodic master-slave\n\n"
            "**radiation**: for isolated structures (absorbing outer boundary)"
        ),
    )
    hbc["type"] = bc_type

    if bc_type == "floquet":
        hbc["n_floquet_modes"] = st.number_input(
            "Number of Floquet modes",
            value=int(hbc.get("n_floquet_modes", 8)),
            help=(
                "8 modes covers up to ~18 GHz for a 20 mm unit cell.\n"
                "Rule: include all modes with |k_t| < k_max at highest frequency."
            ),
        )
    hbc["air_gap_lambda"] = st.number_input(
        "Air box clearance (λ fractions)",
        value=float(hbc.get("air_gap_lambda", 0.25)),
        help="Air box extends this many wavelengths above/below the structure.",
    )

# ─────────────────────────────────────────────────────────────────────────────
with tab_periodic:
    st.subheader("Periodic BCs — Unit Cell Analysis")
    st.markdown("""
    Periodic BCs enforce **u(x + L) = u(x)** by coupling matching nodes on
    opposite faces using MAPDL's CP (constraint equation) command.

    Used for:
    - Representative Volume Element (RVE) homogenization
    - Metamaterial unit cell analysis
    - Floquet mode analysis in HFSS
    """)

    per = bcs.setdefault("periodic", {})
    use_periodic = st.checkbox("Enable periodic BCs", value=bool(per))
    if use_periodic:
        c1, c2 = st.columns(2)
        with c1:
            per["axis"]     = st.selectbox("Periodic axis", ["X","Y","Z"], index=["X","Y","Z"].index(per.get("axis","X")))
            per["lo_coord"] = st.number_input("Lo face coordinate (m)", value=float(per.get("lo_coord", 0.0)))
            per["hi_coord"] = st.number_input("Hi face coordinate (m)", value=float(per.get("hi_coord", 0.01)))
        with c2:
            dof_opts = ["UX","UY","UZ"]
            per["dofs"]     = st.multiselect("Coupled DOFs", dof_opts, default=per.get("dofs", dof_opts))
        bcs["periodic"] = per
    else:
        bcs.pop("periodic", None)

# ── Save ──────────────────────────────────────────────────────────────────────
if st.button("Save Configuration", type="primary"):
    _save_cfg(cfg)
    st.success("Saved")
    st.session_state["cfg"] = cfg
