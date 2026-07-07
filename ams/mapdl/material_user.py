"""TB,USER material wiring + USERMAT DLL env-var linking for the Lemaitre
CDM USERMAT (usermat/usermat_cdm.F).

Ported, near-verbatim, from E:\\Projects\\MAPDL\\mapdl_toolbox\\material.py
(the TB,USER/TBDATA + ANSYS_EM_USER mechanism, proven working in that
project). Only the docstring and the PROP layout (matching usermat_cdm.F's
comment block) changed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def prepare_environment(dll_path) -> None:
    """Set ANS_USER_PATH to the DIRECTORY containing the compiled
    usermatLib.dll. MUST be called before MAPDLRunner.connect()/
    launch_mapdl() so the spawned MAPDL child process inherits the
    environment variable.

    NOTE: this is the variable E:\\Projects\\MAPDL\\mapdl_toolbox\\runner.py
    actually uses to make custom USERMAT solves work (set to the DLL's
    PARENT DIRECTORY, not the DLL file path itself). An earlier version of
    this function set ANSYS_EM_USER (full file path) instead, mirroring that
    project's material.py docstring -- that alone is insufficient; without
    ANS_USER_PATH, ANSYS silently falls back to its internal stub USERMAT
    (which deliberately sets the bisection key every call), producing a
    misleading "the user material routine ... has set the bisection key"
    warning loop and an eventual server crash, regardless of what physics
    is actually written in the custom .F file -- caught by testing a damage-
    law-bypassed diagnostic variant that crashed identically, which only
    makes sense if the real custom code was never being invoked at all.
    """
    dll_path = Path(dll_path)
    os.environ["ANS_USER_PATH"] = str(dll_path.parent)
    log.info("ANS_USER_PATH set to: %s", dll_path.parent)


N_STATEV_CDM = 5   # ustatev(1:5) = [p, D_applied, sigma_e_ratio, D_raw, e1(2)] in usermat_cdm.F


def apply_cdm_user_material(mapdl, mat_id: int, *, E0_Pa: float, nu: float,
                             p_D_pct: float, c: float, m: float,
                             sigma_e0_S_m: float, m_e: float,
                             ratchet_A: float, ratchet_q: float,
                             N_cycle: float = 1.0, h_closure: float = 0.0) -> None:
    """Issue TB,USER + TBDATA for usermat_cdm.F's PROP layout:
      prop(1..11) = [E0, nu, p_D_pct, c, m, sigma_e0, m_e, ratchet_A, ratchet_q,
                     N_cycle, h_closure]

    h_closure (prop 11, default 0.0 = full crack closure in compression) gates
    damage by the LOCAL tension/compression state at each through-thickness
    point (usermat_cdm.F's e1(2) sign check): D_applied = D_raw in tension,
    D_applied = h_closure*D_raw in compression. h_closure=0 means damage has
    NO stiffness effect on the compressive face; h_closure=1 recovers the
    old (ungated) behaviour.

    nProp is inferred from however many TBDATA values are actually issued;
    nStatev is declared separately via TB,STATE (required for SVAR output
    to actually be written to the results file -- without it, OUTRES,SVAR
    is silently ignored and ETABLE,...,SVAR,... fails with "SVAR data is
    not available" at post-processing time).
    """
    params = [E0_Pa, nu, p_D_pct, c, m, sigma_e0_S_m, m_e, ratchet_A, ratchet_q,
              N_cycle, h_closure]

    # Re-issuing TB,USER/TB,STATE for an already-defined mat_id errors with
    # "TB,USER,,,NLIN has already been defined" -- delete first (harmless,
    # ignored, if no table exists yet) so update_cycle_number() can redefine
    # the SAME mat_id's PROP(10)=N_cycle between literal cycles.
    try:
        mapdl.tbdele("STATE", mat_id)
    except Exception:
        pass
    try:
        mapdl.tbdele("USER", mat_id)
    except Exception:
        pass

    mapdl.tb("STATE", mat_id, "", N_STATEV_CDM)
    mapdl.tb("USER", mat_id, "", len(params))
    chunk_size = 6
    for chunk_start in range(0, len(params), chunk_size):
        chunk = params[chunk_start: chunk_start + chunk_size]
        mapdl.tbdata(chunk_start + 1, *chunk)

    log.debug("Material %d (TB,USER / usermat_cdm) defined: %s", mat_id, params)


def update_cycle_number(mapdl, mat_id: int, *, E0_Pa: float, nu: float,
                         p_D_pct: float, c: float, m: float,
                         sigma_e0_S_m: float, m_e: float,
                         ratchet_A: float, ratchet_q: float,
                         N_cycle: float, h_closure: float = 0.0) -> None:
    """Re-issue TB,USER/TBDATA with an updated N_cycle (prop 10) between
    literal cycles -- this is what gives Track B genuine self-consistent
    stiffness feedback: the damage state used by THIS cycle's equilibrium
    solve is re-evaluated from the calibrated ratcheting law at the new
    cycle index, not carried over as a frozen STATEV from cycle 1."""
    apply_cdm_user_material(
        mapdl, mat_id, E0_Pa=E0_Pa, nu=nu, p_D_pct=p_D_pct, c=c, m=m,
        sigma_e0_S_m=sigma_e0_S_m, m_e=m_e,
        ratchet_A=ratchet_A, ratchet_q=ratchet_q, N_cycle=N_cycle,
        h_closure=h_closure,
    )
