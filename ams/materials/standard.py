"""
Standard material models for MAPDL.

Covers the most common continuum material descriptions used in structural,
thermal, and multiphysics FEA.  Each function maps directly to MAPDL
MP/TB/TBDATA commands.

Material models
---------------
1. Elastic (isotropic)          — Hookean spring; E, ν, ρ
2. Elastic-plastic (BISO)       — bilinear isotropic hardening
3. Elastic-plastic (MISO)       — multilinear isotropic hardening
4. Chaboche kinematic hardening — nonlinear kinematic + isotropic (cyclic)
5. Hyperelastic (Neo-Hookean)   — large-strain rubber-like materials
6. Thermal                      — temperature-dependent conductivity, CTE
7. EM material (for MAPDL PLANE53 / SOLID97)

Mathematical background
-----------------------

Isotropic linear elasticity (Hooke's law):
    σ = C : ε
where C is the 4th-order elasticity tensor.  In Voigt notation (6×6 matrix):
    [σ_x]   [C₁₁ C₁₂ C₁₂  0   0   0 ] [ε_x]
    [σ_y]   [C₁₂ C₁₁ C₁₂  0   0   0 ] [ε_y]
    [σ_z] = [C₁₂ C₁₂ C₁₁  0   0   0 ] [ε_z]
    [τ_xy]  [ 0   0   0   C₄₄  0   0 ] [γ_xy]
    [τ_yz]  [ 0   0   0    0  C₄₄  0 ] [γ_yz]
    [τ_xz]  [ 0   0   0    0   0  C₄₄] [γ_xz]

where C₁₁ = E(1-ν)/((1+ν)(1-2ν)), C₁₂ = Eν/((1+ν)(1-2ν)), C₄₄ = E/(2(1+ν)).

Yield criterion (von Mises):
    f(σ) = √(3/2 s:s) - σ_y = 0
where s = σ - 1/3 tr(σ)I is the deviatoric stress.

Flow rule (associated):
    dε^pl = dλ ∂f/∂σ = (3/2) dλ (s / σ_eq)

Isotropic hardening:
    σ_y = σ_y0 + H ε^pl_eq   (linear: H = tangent modulus)
    σ_y = σ_y0 + R(ε^pl_eq)  (nonlinear: specified by MISO table)

Chaboche kinematic hardening (backstress evolution):
    α̇ = (2/3) Cₖ ε̇^pl - γₖ α |ε̇^pl|
where Cₖ, γₖ are material parameters from cyclic tests.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Isotropic linear elasticity
# ─────────────────────────────────────────────────────────────────────────────

def assign_elastic(
    mapdl,
    mat_id: int,
    E_Pa:           float,
    nu:             float,
    density_kg_m3:  float = 0.0,
    name:           str   = "",
) -> None:
    """Define an isotropic linear elastic material.

    Parameters
    ----------
    mapdl : PyMAPDL instance (must be in PREP7)
    mat_id : int
        MAPDL material number (1-based).
    E_Pa : float
        Young's modulus (Pa).  Typical values:
          Steel:    200 GPa (200e9 Pa)
          Aluminum: 70 GPa
          Copper:   110 GPa
          Rubber:   1–10 MPa
    nu : float
        Poisson's ratio (dimensionless).  Typical: 0.28–0.35 for metals.
        Near 0.5 = nearly incompressible — requires mixed u-P formulation.
    density_kg_m3 : float
        Mass density (kg/m³).  Required for modal / transient.
        Steel ≈ 7850, Al ≈ 2700, Copper ≈ 8960.
    name : str
        Label for logging.
    """
    mapdl.prep7()
    mapdl.mp("EX",   mat_id, E_Pa)
    mapdl.mp("PRXY", mat_id, nu)
    if density_kg_m3 > 0:
        mapdl.mp("DENS", mat_id, density_kg_m3)

    log.info(
        "MAT %d (%s): Elastic — E=%.3e Pa, ν=%.4f, ρ=%.1f kg/m³",
        mat_id, name or "unnamed", E_Pa, nu, density_kg_m3,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bilinear isotropic hardening (BISO)
# ─────────────────────────────────────────────────────────────────────────────

def assign_bilinear_plastic(
    mapdl,
    mat_id:           int,
    E_Pa:             float,
    nu:               float,
    density_kg_m3:    float,
    yield_stress_Pa:  float,
    tangent_mod_Pa:   float,
    name:             str = "",
) -> None:
    """Define a bilinear isotropic hardening elastic-plastic material.

    Parameters
    ----------
    yield_stress_Pa : float
        Initial yield stress σ_y0 (Pa).  Typical: 250 MPa for mild steel.
    tangent_mod_Pa : float
        Post-yield tangent modulus E_T = dσ/dε^pl (Pa).
        E_T = 0 → perfect plasticity (no hardening).
        E_T = E → linear hardening (unrealistic, for benchmarks).
        Typical: E_T ≈ 0.001–0.01 × E for metals.

    MAPDL commands
    --------------
    MP,EX,mat_id,E
    MP,PRXY,mat_id,nu
    MP,DENS,mat_id,rho
    TB,BISO,mat_id,1,2      (1 temperature, 2 data pts)
    TBDATA,1,yield,tangent  (σ_y0, E_T)
    """
    assign_elastic(mapdl, mat_id, E_Pa, nu, density_kg_m3, name)
    mapdl.tb("BISO", mat_id, 1, 2)
    mapdl.tbdata(1, yield_stress_Pa, tangent_mod_Pa)

    log.info(
        "MAT %d (%s): BISO — σ_y0=%.3e Pa, E_T=%.3e Pa",
        mat_id, name or "unnamed", yield_stress_Pa, tangent_mod_Pa,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Multilinear isotropic hardening (MISO) — piecewise stress-strain curve
# ─────────────────────────────────────────────────────────────────────────────

def assign_multilinear_plastic(
    mapdl,
    mat_id:          int,
    E_Pa:            float,
    nu:              float,
    density_kg_m3:   float,
    stress_strain:   list[tuple[float, float]],
    name:            str = "",
) -> None:
    """Define a multilinear isotropic hardening material from a stress-strain curve.

    Parameters
    ----------
    stress_strain : list of (strain, stress_Pa) tuples
        Engineering stress-strain data.  The first point MUST be at yield:
        (ε_y = σ_y/E, σ_y).  All subsequent points extend into plastic range.
        Example: [(0.00125, 250e6), (0.005, 280e6), (0.02, 320e6), (0.10, 400e6)]

    Notes
    -----
    MAPDL fits a Ramberg-Osgood curve through the MISO data points for
    intermediate strains.  Ensure the data is monotonically increasing.
    """
    assign_elastic(mapdl, mat_id, E_Pa, nu, density_kg_m3, name)
    n_pts = len(stress_strain)
    mapdl.tb("MISO", mat_id, 1, n_pts)
    for i, (strain, stress) in enumerate(stress_strain):
        mapdl.tbdata(i * 2 + 1, strain, stress)

    log.info(
        "MAT %d (%s): MISO — %d stress-strain points, "
        "σ_y=%.3e Pa at ε=%.4f",
        mat_id, name or "unnamed", n_pts,
        stress_strain[0][1], stress_strain[0][0],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chaboche nonlinear kinematic hardening
# ─────────────────────────────────────────────────────────────────────────────

def assign_chaboche(
    mapdl,
    mat_id:          int,
    E_Pa:            float,
    nu:              float,
    density_kg_m3:   float,
    yield_stress_Pa: float,
    C_params:        list[float],
    gamma_params:    list[float],
    nliso_Q_Pa:      float = 0.0,
    nliso_b:         float = 0.0,
    name:            str = "",
) -> None:
    """Define a Chaboche nonlinear kinematic + isotropic hardening material.

    This model is the gold standard for cyclic plasticity simulation (fatigue
    loading, ratcheting, mean stress relaxation).

    Parameters
    ----------
    C_params : list[float]
        Kinematic hardening moduli Cₖ (Pa) — length = number of backstress terms.
        Typical: 1–3 terms.  Calibrated from cyclic hysteresis loops.
    gamma_params : list[float]
        Dynamic recovery coefficients γₖ (dimensionless).
        Same length as C_params.
    nliso_Q_Pa : float
        Saturated isotropic hardening R_∞ (Pa).  0 = no cyclic hardening/softening.
    nliso_b : float
        Rate of isotropic hardening evolution (dimensionless).

    Model equations
    ---------------
    Backstress (k-th term):
        α̇ₖ = (2/3) Cₖ ε̇^pl - γₖ α̇ₖ ṗ
    where ṗ = |dε^pl| (accumulated plastic strain rate).

    Total backstress:
        X = Σₖ αₖ

    Yield condition (kinematic):
        f(σ, X) = √(3/2 (s - X):(s - X)) - σ_y(p) = 0
        σ_y(p) = σ_y0 + Q_∞(1 - e^{-bp})    (isotropic part)
    """
    n_back = len(C_params)
    if len(gamma_params) != n_back:
        raise ValueError("C_params and gamma_params must have the same length")

    assign_elastic(mapdl, mat_id, E_Pa, nu, density_kg_m3, name)

    # TB,CHABOCHE for kinematic hardening
    mapdl.tb("CHABOCHE", mat_id, 1, n_back)
    for i, (C, g) in enumerate(zip(C_params, gamma_params)):
        mapdl.tbdata(i * 2 + 1, C, g)

    # TB,NLISO for isotropic hardening component
    if nliso_Q_Pa != 0.0:
        mapdl.tb("NLISO", mat_id, 1, 2)
        mapdl.tbdata(1, yield_stress_Pa, nliso_Q_Pa, nliso_b, 0.0)

    log.info(
        "MAT %d (%s): Chaboche — %d backstress terms, "
        "σ_y0=%.3e Pa",
        mat_id, name or "unnamed", n_back, yield_stress_Pa,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Neo-Hookean hyperelastic (large-strain rubber)
# ─────────────────────────────────────────────────────────────────────────────

def assign_neohookean(
    mapdl,
    mat_id:       int,
    mu_Pa:        float,
    d1_1_Pa:      float,
    density_kg_m3: float = 0.0,
    name:         str   = "",
) -> None:
    """Define a Neo-Hookean hyperelastic material for large-strain analysis.

    Strain energy density:
        W = μ/2 (Ī₁ - 3) + 1/d₁ (J - 1)²
    where:
        Ī₁ = J^{-2/3} I₁   (first deviatoric invariant)
        I₁ = tr(B) = λ₁² + λ₂² + λ₃²  (principal stretches)
        J  = det(F)          (volume change)
        μ  = shear modulus   (≈ E/3 for incompressible rubber)
        d₁ = bulk compliance (≈ 2/K, K = bulk modulus)

    Connection to linear elasticity (small strain limit):
        μ ≈ E/(2(1+ν)),   d₁ ≈ 2(1-2ν)/E

    Parameters
    ----------
    mu_Pa : float
        Initial shear modulus (Pa).
    d1_1_Pa : float
        Compressibility parameter d₁ (Pa⁻¹).  Use 0 for fully incompressible.
        For nearly incompressible (ν=0.499): d₁ ≈ 2×(1-2×0.499)/E.
    """
    assign_elastic(mapdl, mat_id, mu_Pa * 3, 0.499, density_kg_m3, name)  # fallback for small strain
    mapdl.tb("HYPER", mat_id, 1, "", "NEO")
    mapdl.tbdata(1, mu_Pa, d1_1_Pa)

    log.info(
        "MAT %d (%s): Neo-Hookean — μ=%.3e Pa, d₁=%.3e Pa⁻¹",
        mat_id, name or "unnamed", mu_Pa, d1_1_Pa,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Config-driven dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def apply_materials(mapdl, cfg: dict) -> None:
    """Apply all materials defined in the 'materials' section of config.yaml.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    cfg : dict
        The full config dict (top-level, not just 'materials').
    """
    for mat in cfg.get("materials", []):
        mat_id = int(mat.get("mat_id", 1))
        model  = mat.get("model", "elastic").lower()
        name   = mat.get("name", f"material_{mat_id}")

        if model == "elastic":
            assign_elastic(
                mapdl, mat_id,
                E_Pa           = float(mat["E_Pa"]),
                nu             = float(mat["nu"]),
                density_kg_m3  = float(mat.get("density_kg_m3", 0.0)),
                name           = name,
            )

        elif model == "bilinear_plastic":
            pl = mat.get("plasticity", {})
            assign_bilinear_plastic(
                mapdl, mat_id,
                E_Pa            = float(mat["E_Pa"]),
                nu              = float(mat["nu"]),
                density_kg_m3   = float(mat.get("density_kg_m3", 0.0)),
                yield_stress_Pa = float(pl["yield_stress_Pa"]),
                tangent_mod_Pa  = float(pl["tangent_modulus_Pa"]),
                name            = name,
            )

        elif model == "chaboche":
            ch = mat.get("chaboche", {})
            assign_chaboche(
                mapdl, mat_id,
                E_Pa             = float(mat["E_Pa"]),
                nu               = float(mat["nu"]),
                density_kg_m3    = float(mat.get("density_kg_m3", 0.0)),
                yield_stress_Pa  = float(ch["yield_stress_Pa"]),
                C_params         = [float(x) for x in ch.get("C", [])],
                gamma_params     = [float(x) for x in ch.get("gamma", [])],
                nliso_Q_Pa       = float(ch.get("Q_Pa", 0.0)),
                nliso_b          = float(ch.get("b", 0.0)),
                name             = name,
            )

        elif model == "neohookean":
            assign_neohookean(
                mapdl, mat_id,
                mu_Pa         = float(mat["mu_Pa"]),
                d1_1_Pa       = float(mat["d1_Pa"]),
                density_kg_m3 = float(mat.get("density_kg_m3", 0.0)),
                name          = name,
            )

        elif model == "usermat":
            # USERMAT: compiled Fortran material — just set nparams
            n_params = int(mat.get("n_params", 4))
            n_statev = int(mat.get("n_state_vars", 0))
            mapdl.tb("USER", mat_id)
            mapdl.tbdata(1, *[float(mat.get(f"p{i+1}", 0.0)) for i in range(n_params)])
            log.info(
                "MAT %d (%s): USERMAT — %d params, %d state vars",
                mat_id, name, n_params, n_statev,
            )

        else:
            log.warning("Unknown material model '%s' for MAT %d — skipped", model, mat_id)
