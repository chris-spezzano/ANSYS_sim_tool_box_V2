"""
MAPDL Solver Strategy — configure and execute the FE solver.

Solver types
------------
  static       : time-independent equilibrium (most common)
  modal        : natural frequencies and mode shapes
  harmonic     : steady-state response under sinusoidal loading
  transient    : time-domain dynamics (explicit or implicit)
  buckling     : linearized prebuckling stability analysis

Newton-Raphson variants (for nonlinear static)
----------------------------------------------
  FULL    : reassemble and factor [K_T] every iteration.
            Quadratic convergence near the solution.
            Slowest per iteration, fewest iterations for strong nonlinearity.

  MODI    : modified NR — factor [K_T] once per load step, iterate with
            the same tangent.  Faster per iteration; more iterations needed.
            Good when the stiffness does not change much within a step.

  INIT    : initial stiffness — always use the elastic [K].
            Never reassembles.  Slowest convergence but never diverges.
            Use as a fallback when FULL NR diverges.

  UNSYM   : unsymmetric tangent (e.g., follower forces, non-associated plasticity).
            Requires a full unsymmetric factorization (2× cost of symmetric).

Convergence criteria
--------------------
MAPDL checks convergence using L2 norms:
    Force residual:       ‖R‖₂ / ‖F_ref‖₂  <  ε_F    (default 0.5%)
    Displacement change:  ‖Δu‖₂ / ‖u_ref‖₂  <  ε_U   (default 0.5%)

Both criteria must be satisfied simultaneously.  Tightening to 0.1% gives
more accurate results but ~2–4× more iterations.

Retry/escalation ladder
-----------------------
When the NR algorithm fails to converge within NEQIT iterations:
  Level 1 (default):    AUTOTS bisects the load step and retries
  Level 2:              STABILIZE adds artificial energy damping
  Level 3:              ARCLEN activates arc-length method (snap-through/buckling)
  Level 4:              Two-stage split — solve to 50% then restart to 100%

Line search (LNSRCH)
--------------------
The standard NR step is:  u_{n+1} = u_n - [K_T]⁻¹ R_n  (full step)
Line search scales this: u_{n+1} = u_n - α [K_T]⁻¹ R_n  (α ∈ (0,1])
where α is chosen to minimize ‖R(u + α Δu)‖.
Line search helps for strongly nonlinear problems but adds function evaluations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class SolverStrategy:
    """Configuration for the MAPDL solver.

    Attributes mirror the 'solver' section of config.yaml.
    """
    type:              str   = "static"
    nlgeom:            bool  = False
    nsubsteps_initial: int   = 10
    nsubsteps_max:     int   = 100
    nsubsteps_min:     int   = 1
    autots:            bool  = True
    nropt:             str   = "FULL"
    lnsrch:            bool  = True
    neqit:             int   = 25        # max NR iterations per substep
    cnvtol_force:      float = 0.005     # force convergence tolerance (0.5%)
    cnvtol_disp:       float = 0.005     # displacement convergence tolerance
    stabilize:         bool  = False
    stabilize_energy:  float = 0.05      # max artificial/total energy ratio
    arclen:            bool  = False
    retry_enabled:     bool  = True
    retry_max_level:   int   = 4
    n_modes:           int   = 10        # for modal analysis
    freq_start_Hz:     float = 0.0       # for modal / harmonic
    freq_end_Hz:       float = 10000.0
    n_substeps_harm:   int   = 100       # for harmonic
    damping_ratio:     float = 0.02      # for harmonic / transient

    @classmethod
    def from_config(cls, cfg: dict) -> "SolverStrategy":
        """Build SolverStrategy from the 'solver' section of the config."""
        s = cfg.get("solver", {})
        nsub = s.get("nsubst", s.get("nsubsteps", {}))
        if isinstance(nsub, dict):
            nsub_init = nsub.get("initial", 10)
            nsub_max  = nsub.get("max", 100)
            nsub_min  = nsub.get("min", 1)
        else:
            nsub_init = nsub_max = nsub_min = int(nsub)

        retry = s.get("retry", {})
        modal = s.get("modal", {})
        harm  = s.get("harmonic", {})

        return cls(
            type              = s.get("type", "static"),
            nlgeom            = bool(s.get("nlgeom", False)),
            nsubsteps_initial = nsub_init,
            nsubsteps_max     = nsub_max,
            nsubsteps_min     = nsub_min,
            autots            = bool(s.get("autots", True)),
            nropt             = str(s.get("nropt", "FULL")).upper(),
            lnsrch            = bool(s.get("lnsrch", True)),
            neqit             = int(s.get("neqit", 25)),
            cnvtol_force      = float(s.get("cnvtol_force", 0.005)),
            cnvtol_disp       = float(s.get("cnvtol_disp", 0.005)),
            stabilize         = bool(s.get("stabilize", False)),
            stabilize_energy  = float(retry.get("stabilize_energy_ratio", 0.05)),
            arclen            = bool(s.get("arclen", False)),
            retry_enabled     = bool(retry.get("enabled", True)),
            retry_max_level   = int(retry.get("max_level", 4)),
            n_modes           = int(modal.get("n_modes", 10)),
            freq_start_Hz     = float(modal.get("freq_range_Hz", [0.0, 10000.0])[0]),
            freq_end_Hz       = float(modal.get("freq_range_Hz", [0.0, 10000.0])[1]),
            n_substeps_harm   = int(harm.get("n_substeps", 100)),
            damping_ratio     = float(harm.get("damping_ratio", 0.02)),
        )


def run_solution(mapdl, cfg_or_strategy, load_step: int = 1) -> None:
    """Configure and execute the MAPDL solution.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    cfg_or_strategy : dict | SolverStrategy
        Either the raw solver config dict or a pre-built SolverStrategy.
    load_step : int
        Load step number (default 1).  Increment for multi-step analyses.
    """
    if isinstance(cfg_or_strategy, dict):
        s = SolverStrategy.from_config(cfg_or_strategy)
    else:
        s = cfg_or_strategy

    solve_fn = {
        "static":    _solve_static,
        "modal":     _solve_modal,
        "harmonic":  _solve_harmonic,
        "transient": _solve_transient,
        "buckling":  _solve_buckling,
    }.get(s.type.lower())

    if solve_fn is None:
        raise ValueError(
            f"Unknown solver type '{s.type}'. "
            f"Valid types: static, modal, harmonic, transient, buckling"
        )

    solve_fn(mapdl, s)


# ─────────────────────────────────────────────────────────────────────────────
# Solver implementations
# ─────────────────────────────────────────────────────────────────────────────

def _solve_static(mapdl, s: SolverStrategy) -> None:
    """Configure and run a static structural analysis.

    Algorithm (FULL Newton-Raphson with automatic time stepping)
    ============================================================
    1. Predictor: u_pred = u_{n-1} + (Δt/Δt_{n-1}) × Δu_{n-1}
    2. Corrector iterations (k = 1, 2, ... NEQIT):
       a. Evaluate internal forces:  F_int = ∫ B^T σ dV
       b. Compute residual:          R = F_ext - F_int - F_inertia
       c. Check convergence:         ‖R‖/‖F_ref‖ < ε_F  AND  ‖Δu‖/‖u_ref‖ < ε_U
       d. If not converged: solve    [K_T] Δu = R  → update u
    3. If substep diverges and AUTOTS=ON: bisect Δt and retry
    4. If all bisections fail: escalate to STABILIZE or ARCLEN

    Reference: ANSYS Mechanical APDL Theory Reference, §15 "Nonlinear Analysis".
    """
    mapdl.run("/SOLU")
    mapdl.antype("STATIC")

    # Large deformation (geometric nonlinearity)
    mapdl.nlgeom("ON" if s.nlgeom else "OFF")

    # Substep control — automatic time stepping
    mapdl.nsubst(s.nsubsteps_initial, s.nsubsteps_max, s.nsubsteps_min)
    if s.autots:
        mapdl.autots("ON")

    # Newton-Raphson variant
    mapdl.nropt(s.nropt)

    # Convergence tolerances
    mapdl.cnvtol("F", "", s.cnvtol_force)  # force residual
    mapdl.cnvtol("U", "", s.cnvtol_disp)  # displacement correction

    # Max iterations per substep
    mapdl.neqit(s.neqit)

    # Line search
    mapdl.lnsrch("ON" if s.lnsrch else "OFF")

    # Stabilization (artificial damping for local instabilities)
    if s.stabilize:
        mapdl.stabilize("CONSTANT", "ENERGY", s.stabilize_energy)
        log.info("STABILIZE active: energy ratio = %.3f", s.stabilize_energy)

    # Arc-length method (snap-through / post-buckling)
    if s.arclen:
        mapdl.arclen("ON")
        log.info("Arc-length method active")

    # Write all result sets (substeps) to RST for animation and diagnostics
    mapdl.outres("ALL", "ALL")

    log.info(
        "Static solve: nlgeom=%s, nropt=%s, nsubst=(%d,%d,%d), neqit=%d",
        s.nlgeom, s.nropt,
        s.nsubsteps_initial, s.nsubsteps_max, s.nsubsteps_min,
        s.neqit,
    )
    mapdl.solve()
    mapdl.finish()
    log.info("Static solution complete")


def _solve_modal(mapdl, s: SolverStrategy) -> None:
    """Configure and run a modal (eigenvalue) analysis.

    Extracts natural frequencies ωₙ and mode shapes φₙ via:
        [K - ωₙ² M] φₙ = 0

    MAPDL uses the Block Lanczos method (MODOPT,LANB) by default — a
    Krylov-subspace eigensolver that efficiently finds the lowest n_modes
    eigenvalues without factoring the full matrix.

    The characteristic equation det([K] - ω²[M]) = 0 has n_dof solutions
    (n_dof = total degrees of freedom), but typically only the lowest
    n_modes frequencies are physically meaningful for structural design.
    """
    mapdl.run("/SOLU")
    mapdl.antype("MODAL")

    # Block Lanczos: most reliable for structural FEM (symmetric [K], [M])
    mapdl.modopt("LANB", s.n_modes, s.freq_start_Hz, s.freq_end_Hz)
    mapdl.mxpand(s.n_modes)   # expand mode shapes for post-processing
    mapdl.outres("ALL", "ALL")

    log.info(
        "Modal solve: %d modes, freq range [%.1f, %.1f] Hz",
        s.n_modes, s.freq_start_Hz, s.freq_end_Hz,
    )
    mapdl.solve()
    mapdl.finish()
    log.info("Modal analysis complete")


def _solve_harmonic(mapdl, s: SolverStrategy) -> None:
    """Configure and run a harmonic response analysis.

    Computes the steady-state response to a sinusoidal load F(t) = F₀ e^{iωt}:
        [K + iωC - ω²M] U(ω) = F₀

    where C is the damping matrix.  The solution U(ω) is complex:
        U(ω) = U_real(ω) + i·U_imag(ω)
    Amplitude: |U(ω)| = √(U_real² + U_imag²)
    Phase:     φ(ω)   = arctan(U_imag / U_real)

    The frequency response function (FRF) is:
        H(ω) = U(ω) / F₀ = [K + iωC - ω²M]⁻¹

    This is solved for each frequency point using the full method (FULL)
    or mode superposition (MSUP) — MSUP is faster but requires a prior modal run.
    """
    mapdl.run("/SOLU")
    mapdl.antype("HARMIC")
    mapdl.hropt("FULL")
    mapdl.harfrq(s.freq_start_Hz, s.freq_end_Hz)
    mapdl.nsubst(s.n_substeps_harm)
    mapdl.dmprat(s.damping_ratio)   # constant modal damping ratio ξ
    mapdl.outres("ALL", "ALL")

    log.info(
        "Harmonic solve: [%.1f, %.1f] Hz, %d pts, damping=%.3f",
        s.freq_start_Hz, s.freq_end_Hz, s.n_substeps_harm, s.damping_ratio,
    )
    mapdl.solve()
    mapdl.finish()
    log.info("Harmonic analysis complete")


def _solve_transient(mapdl, s: SolverStrategy) -> None:
    """Configure and run a transient (time-domain) dynamic analysis.

    Newmark-β time integration:
        M ü + C u̇ + K u = F(t)

    Newmark-β method (unconditionally stable for β ≥ (1+γ)²/4):
        u_{n+1} = u_n + Δt u̇_n + Δt²[(0.5-β)ü_n + β ü_{n+1}]
        u̇_{n+1} = u̇_n + Δt[(1-γ)ü_n + γ ü_{n+1}]

    Standard parameters (Newmark average acceleration):
        β = 0.25, γ = 0.5 → unconditionally stable, second-order accurate.

    HHT-α method (default in MAPDL for nonlinear transient):
        Higher numerical damping of high-frequency modes (α ∈ [-1/3, 0]).
        Reduces spurious oscillations in contact/plasticity problems.
    """
    mapdl.run("/SOLU")
    mapdl.antype("TRANS")
    mapdl.nlgeom("ON" if s.nlgeom else "OFF")
    mapdl.nsubst(s.nsubsteps_initial, s.nsubsteps_max, s.nsubsteps_min)
    if s.autots:
        mapdl.autots("ON")
    mapdl.lnsrch("ON" if s.lnsrch else "OFF")
    mapdl.tintp("HHT")     # HHT-α integration (robust for nonlinear)
    mapdl.outres("ALL", "ALL")

    log.info("Transient solve configured (HHT-α integration)")
    mapdl.solve()
    mapdl.finish()
    log.info("Transient analysis complete")


def _solve_buckling(mapdl, s: SolverStrategy) -> None:
    """Linearized eigenvalue buckling analysis.

    Buckling load factor λ satisfies:
        [K + λ K_σ] φ = 0

    where K_σ is the stress-stiffness (geometric stiffness) matrix,
    assembled from the pre-stress state (requires a prior static solve).

    Usage workflow
    --------------
    1. Apply a reference load P_ref and run a static solve.
    2. Run buckling analysis → get eigenvalue λ.
    3. Critical buckling load: P_cr = λ × P_ref.

    Euler column buckling (beam, length L, both ends pinned):
        P_cr = π² EI / L²   (Euler, 1744)
    Verify that FEA result matches within 1–2% for slender beams.
    """
    # Step 1: static pre-stress solve (must already be done externally)
    # Step 2: buckling eigenvalue extraction
    mapdl.run("/SOLU")
    mapdl.antype("BUCKLE")
    mapdl.bucopt("LANB", s.n_modes)
    mapdl.mxpand(s.n_modes)
    mapdl.outres("ALL", "ALL")

    log.info("Buckling solve: %d eigenvalues", s.n_modes)
    mapdl.solve()
    mapdl.finish()
    log.info("Buckling analysis complete")


# ─────────────────────────────────────────────────────────────────────────────
# Solver diagnostics helpers (used by LiveDashboard)
# ─────────────────────────────────────────────────────────────────────────────

def parse_solve_status(mapdl) -> dict[str, Any]:
    """Read convergence status from the live MAPDL session.

    Returns
    -------
    dict with keys:
        converged : bool
        substep   : int
        iteration : int
        f_residual: float | None
        u_residual: float | None
        time      : float
    """
    try:
        substep  = int(float(mapdl.get("_SS_",  "ACTIVE", 0, "SOLU", "NCMSS")))
        iteration= int(float(mapdl.get("_IT_",  "ACTIVE", 0, "SOLU", "ITER")))
        time_val = float(mapdl.get("_TM_",  "ACTIVE", 0, "SOLU", "TIME"))
        f_res    = float(mapdl.get("_FNR_", "ACTIVE", 0, "SOLU", "RESD"))
        u_res    = float(mapdl.get("_UNR_", "ACTIVE", 0, "SOLU", "RESDNRM"))
        converged = mapdl.solution.converged if hasattr(mapdl.solution, "converged") else None
    except Exception:
        substep = iteration = 0
        time_val = f_res = u_res = 0.0
        converged = None

    return {
        "converged":  converged,
        "substep":    substep,
        "iteration":  iteration,
        "f_residual": f_res,
        "u_residual": u_res,
        "time":       time_val,
    }
