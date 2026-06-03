"""Page 5 — Solver: Newton-Raphson, convergence settings, retry ladder."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="Solver", layout="wide")
st.title("Step 5 · Solver Strategy")
st.markdown("See **notebooks/05_solver_selection_and_strategy.ipynb** for full NR derivations and convergence theory.")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh: return yaml.safe_load(fh)
    return {}

def _save_cfg(cfg):
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

cfg = _load_cfg()
s = cfg.setdefault("solver", {})

tab_type, tab_nr, tab_conv, tab_retry = st.tabs([
    "Analysis Type", "Newton-Raphson", "Convergence", "Retry Ladder"
])

with tab_type:
    s["type"] = st.selectbox(
        "Analysis type",
        ["static", "modal", "harmonic", "transient", "buckling"],
        index=["static","modal","harmonic","transient","buckling"].index(s.get("type","static")),
    )
    s["nlgeom"] = st.checkbox(
        "Large deformation (NLGEOM ON)",
        value=bool(s.get("nlgeom", False)),
        help=(
            "Enable geometric nonlinearity (large displacements / rotations).\n"
            "Required when: displacements > ~5% of characteristic dimension,\n"
            "thin shells with buckling risk, rubber-like materials."
        ),
    )

    if s["type"] == "static":
        nsub = s.setdefault("nsubst", {})
        c1, c2, c3 = st.columns(3)
        nsub["initial"] = c1.number_input("Initial substeps", value=int(nsub.get("initial", 10)))
        nsub["max"]     = c2.number_input("Max substeps",     value=int(nsub.get("max",     100)))
        nsub["min"]     = c3.number_input("Min substeps",     value=int(nsub.get("min",       1)))
        s["autots"]     = st.checkbox("Auto time-stepping (AUTOTS ON)", value=bool(s.get("autots", True)))

    elif s["type"] == "modal":
        modal = s.setdefault("modal", {})
        modal["n_modes"] = st.number_input("Number of modes", value=int(modal.get("n_modes", 10)))
        c1, c2 = st.columns(2)
        freq_range = modal.get("freq_range_Hz", [0.0, 10000.0])
        modal["freq_range_Hz"] = [
            c1.number_input("Freq start (Hz)", value=float(freq_range[0])),
            c2.number_input("Freq end (Hz)",   value=float(freq_range[1])),
        ]

    elif s["type"] == "harmonic":
        harm = s.setdefault("harmonic", {})
        c1, c2, c3 = st.columns(3)
        harm["freq_start_Hz"] = c1.number_input("Start freq (Hz)",  value=float(harm.get("freq_start_Hz",  10.0)))
        harm["freq_end_Hz"]   = c2.number_input("End freq (Hz)",    value=float(harm.get("freq_end_Hz",  1000.0)))
        harm["n_substeps"]    = c3.number_input("Freq points",      value=int(harm.get("n_substeps",  100)))
        harm["damping_ratio"] = st.slider("Damping ratio ξ", 0.001, 0.20, float(harm.get("damping_ratio", 0.02)))
        st.caption(f"ξ = {harm['damping_ratio']:.3f} → Q ≈ {1/(2*harm['damping_ratio']):.1f}")

with tab_nr:
    st.markdown("""
    ### Newton-Raphson Variants

    The NR algorithm solves the nonlinear system **R(u) = 0** iteratively:

    > **u_{n+1} = u_n − [K_T(u_n)]⁻¹ R(u_n)**

    | Variant | Tangent update | Convergence | Cost/iteration |
    |---------|---------------|-------------|----------------|
    | FULL    | Every iteration | Quadratic  | Highest (refactorize each step) |
    | MODI    | Once per substep | Linear     | Medium |
    | INIT    | Never (use elastic K) | Slowest | Lowest — never diverges |
    | UNSYM   | Unsymmetric tangent | Quadratic | 2× FULL |
    """)
    s["nropt"] = st.selectbox(
        "NR variant",
        ["FULL", "MODI", "INIT", "UNSYM"],
        index=["FULL","MODI","INIT","UNSYM"].index(s.get("nropt","FULL")),
        help=(
            "FULL: best for strongly nonlinear problems (plasticity, contact, large rotation)\n"
            "MODI: use when stiffness changes slowly (mild nonlinearity)\n"
            "INIT: fallback when FULL diverges\n"
            "UNSYM: required for follower forces or non-associated plasticity"
        ),
    )
    s["lnsrch"] = st.checkbox(
        "Line search (LNSRCH ON)",
        value=bool(s.get("lnsrch", True)),
        help=(
            "Scales the NR step: u_{n+1} = u_n − α [K_T]⁻¹ R_n\n"
            "α is chosen by a 1D minimization of ‖R‖.\n"
            "Helps convergence for highly nonlinear problems but adds function evaluations."
        ),
    )

with tab_conv:
    st.markdown("""
    ### Convergence Criteria

    MAPDL checks TWO criteria simultaneously:

    > Force:        **‖R‖₂ / ‖F_ref‖₂ < ε_F**
    >
    > Displacement: **‖Δu‖₂ / ‖u_ref‖₂ < ε_U**

    Both must be satisfied in the same iteration.
    """)
    c1, c2, c3 = st.columns(3)
    s["cnvtol_force"] = c1.number_input(
        "Force tolerance ε_F", value=float(s.get("cnvtol_force", 0.005)),
        format="%.4f", help="Default 0.005 = 0.5%.  Tighten to 0.001 for precision."
    )
    s["cnvtol_disp"]  = c2.number_input(
        "Displacement tolerance ε_U", value=float(s.get("cnvtol_disp", 0.005)),
        format="%.4f"
    )
    s["neqit"]        = c3.number_input(
        "Max NR iterations (NEQIT)", value=int(s.get("neqit", 25)),
        help="Substep bisects if this limit is reached."
    )

with tab_retry:
    st.markdown("""
    ### Retry / Escalation Ladder

    When the solver diverges, MAPDL escalates through progressively more
    aggressive strategies:

    | Level | Strategy | Activated by |
    |-------|----------|-------------|
    | 1 | AUTOTS bisection | Default — always on |
    | 2 | STABILIZE (artificial damping) | Manual or auto |
    | 3 | ARCLEN (arc-length) | Manual only |
    | 4 | Two-stage load split | Manual only |
    """)
    retry = s.setdefault("retry", {})
    retry["enabled"]   = st.checkbox("Enable retry ladder", value=bool(retry.get("enabled", True)))
    retry["max_level"] = st.slider("Max retry level", 1, 4, int(retry.get("max_level", 4)))

    st.markdown("**Level 2 — STABILIZE**")
    s["stabilize"] = st.checkbox(
        "Pre-activate STABILIZE",
        value=bool(s.get("stabilize", False)),
        help=(
            "Adds artificial energy-damping to pass local instabilities.\n"
            "Check: AENE/SENE < 5% (artificial energy < 5% of total strain energy)."
        ),
    )
    if s["stabilize"]:
        retry["stabilize_energy_ratio"] = st.number_input(
            "Max artificial energy ratio (AENE/SENE)",
            value=float(retry.get("stabilize_energy_ratio", 0.05)),
            format="%.3f",
        )

    st.markdown("**Level 3 — Arc-Length**")
    s["arclen"] = st.checkbox(
        "Pre-activate Arc-Length method",
        value=bool(s.get("arclen", False)),
        help=(
            "For snap-through or post-buckling (structural instability).\n"
            "The arc-length method follows the solution curve even past limit points.\n"
            "Do NOT combine with AUTOTS."
        ),
    )

if st.button("Save Configuration", type="primary"):
    _save_cfg(cfg)
    st.success("Saved")
    st.session_state["cfg"] = cfg
