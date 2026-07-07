"""
HFSS Boundary Condition Assignments via PyAEDT.

Supported BC types
------------------
1. Perfect Electric Conductor (PEC)    — σ → ∞ surface (ideal metal)
2. Finite Conductivity                 — realistic lossy metal (copper, steel)
3. Floquet Port                        — periodic unit cell excitation
4. Periodic Master-Slave              — infinite periodicity in XY plane
5. Radiation                           — absorbing outer boundary (free space)
6. Lumped Port                         — coaxial/gap excitation
7. Wave Port                           — full-wave guided-mode excitation

Mathematical basis
------------------
The boundary conditions enforce the tangential field matching at interfaces.

PEC (σ → ∞):  n × E = 0  on Γ_PEC    (electric field is normal only)
PMC:           n × H = 0  on Γ_PMC    (magnetic field is normal only)

Floquet port — periodic excitation with oblique incidence:
    The Floquet modes are plane waves with:
        E(r) = E₀ exp(-j k · r)   where k = k_t + k_z ẑ
    k_t = k_x x̂ + k_y ŷ  (transverse wavevector, set by incidence angle)
    HFSS solves for the mode amplitudes (reflection/transmission coefficients)

Periodic BCs (Master-Slave):
    Fields on slave face = phase-shifted copy of master face:
        E_slave = E_master × exp(-j k_t · L)
    where L is the unit-cell lattice vector.

Reference: David M. Pozar, "Microwave Engineering", 4th Ed. §4 (waveguides).
           Constantine A. Balanis, "Advanced Engineering Electromagnetics", §6.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


def assign_finite_conductivity(
    hfss,
    object_name: str,
    conductivity_S_m: float,
    thickness_m: float | None = None,
    name: str = "FiniteCond",
) -> None:
    """Assign a finite conductivity boundary to a surface object.

    Used for realistic metal sheets (copper origami, PCB traces, etc.).
    Unlike PEC, this models skin-effect losses.

    Physical model: impedance boundary condition (IBC):
        n × H = (1 + j) / (2 δ σ) × (n × (n × H))
    where δ = √(2/(ωμσ)) is the skin depth.

    Parameters
    ----------
    hfss : HFSS object
    object_name : str
        Name of the geometric object (face / solid) to assign to.
    conductivity_S_m : float
        Electrical conductivity σ (S/m).
        Common values: copper 5.8e7, aluminum 3.7e7, steel 1.1e7.
    thickness_m : float | None
        Sheet thickness.  If provided, HFSS uses the 'Layered Impedance' model
        which is more accurate for sheets thinner than the skin depth.
    name : str
        BC assignment name.
    """
    try:
        kwargs: dict[str, Any] = {
            "conductivity": conductivity_S_m,
            "name": name,
        }
        if thickness_m is not None:
            kwargs["thickness"] = thickness_m

        hfss.assign_finite_conductivity(object_name, **kwargs)
        skin_depth_1GHz = np.sqrt(2 / (2 * np.pi * 1e9 * 4 * np.pi * 1e-7 * conductivity_S_m))
        log.info(
            "Finite conductivity BC '%s': σ=%.3e S/m, δ(1GHz)=%.2f µm",
            name, conductivity_S_m, skin_depth_1GHz * 1e6,
        )
    except Exception as exc:
        log.error("Failed to assign finite conductivity to '%s': %s", object_name, exc)
        raise


def assign_pec(hfss, object_name: str, name: str = "PEC") -> None:
    """Assign a Perfect Electric Conductor (PEC) boundary.

    Use for: ideal metal walls, ground planes, waveguide walls.
    n × E = 0 on the PEC surface.
    """
    hfss.assign_perfect_e(object_name, name=name)
    log.info("PEC boundary '%s' assigned to '%s'", name, object_name)


def assign_radiation_boundary(hfss, air_box_name: str, name: str = "Radiation") -> None:
    """Assign a radiation (absorbing) boundary to the outer air box.

    Use for isolated scatterer analysis (not periodic).
    Implements a first-order absorbing boundary condition:
        n × ∇ × E + jk₀ (n × (n × E)) = 0  on Γ_∞

    Parameters
    ----------
    air_box_name : str
        Name of the outer air box solid object.
    """
    hfss.assign_radiation(air_box_name, name=name)
    log.info("Radiation boundary '%s' assigned to '%s'", name, air_box_name)


def assign_floquet_ports(
    hfss,
    air_box_name: str,
    propagation_axis: str = "Z",
    n_modes: int = 2,
    name_prefix: str = "FloquetPort",
) -> tuple[str, str]:
    """Assign a Floquet port to EACH of the two air-box faces normal to
    propagation_axis (e.g. top and bottom, for the default Z axis) -- a
    single create_floquet_port() call only ever assigns ONE port, so a
    Floquet-port pair (required for any S11/S21 transmission measurement)
    needs two separate calls. Confirmed against the installed PyAEDT 1.1.0
    API directly (this session): the real Hfss.create_floquet_port()
    signature takes assignment/modes/name/reporter_filter/deembed_distance
    -- NOT the assignment/nummodes/reportfilter/deembedding names an earlier
    version of this function used, which do not exist on this class and
    would raise TypeError if called.

    lattice_origin/lattice_a_end/lattice_b_end are computed explicitly here
    (NOT left at the PyAEDT default of None) using the SAME A/B convention
    for both faces. Confirmed this session that leaving both at None lets
    each face auto-detect its own lattice vectors independently, and AEDT's
    own design validation then rejects the pair with "Your problem setup
    includes two Floquet Ports ... They are required to have the same
    lattice coordinate systems and phase delays" -- the auto-detected A/B
    sense differs between the two faces (they face opposite normals) even
    though the unit cell itself is a simple rectangle.

    Floquet ports model plane wave excitation of an infinite periodic array.
    Mode 1: TE(0,0) (normally incident TE plane wave); mode 2: TM(0,0).
    Higher modes are evanescent. n_modes=2 (just the fundamental pair) is
    enough whenever the unit cell is well below lambda/2 at the frequency of
    interest, so no higher-order Floquet mode actually propagates -- check
    this for your own geometry/frequency before trusting n_modes=2 elsewhere.

    S-parameters convention
    -----------------------
    S11 = reflection coefficient (port 1, mode 1)
    S21 = transmission coefficient (port 1 -> port 2, mode 1)
    SE (shielding effectiveness) = -20 log10|S21| dB

    Returns (port1_name, port2_name).
    """
    axis_idx = {"X": 0, "Y": 1, "Z": 2}[propagation_axis.upper()]
    u_idx, v_idx = [i for i in range(3) if i != axis_idx]
    # hfss.modeler[name] (Modeler3D.__getitem__) is the confirmed-working
    # object-by-name lookup for this PyAEDT version -- a "objects.get(name)"
    # variant tried earlier returned None silently instead of raising,
    # masking the real bug until the .faces access below failed instead.
    air_box = hfss.modeler[air_box_name]
    faces_sorted = sorted(air_box.faces, key=lambda f: f.center[axis_idx])
    lo_face, hi_face = faces_sorted[0], faces_sorted[-1]

    # Build identical-convention A/B lattice vectors for both faces (same
    # u/v half-extents, same vertex traversal order) -- see docstring for
    # why leaving these at PyAEDT's auto-detect default fails validation.
    u_vals = [v.position[u_idx] for v in hi_face.vertices]
    v_vals = [v.position[v_idx] for v in hi_face.vertices]
    u_lo, u_hi = min(u_vals), max(u_vals)
    v_lo, v_hi = min(v_vals), max(v_vals)

    def _lattice_points(face):
        origin, a_end, b_end = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        z = face.center[axis_idx]
        for pt in (origin, a_end, b_end):
            pt[axis_idx] = z
        origin[u_idx], origin[v_idx] = u_lo, v_lo
        a_end[u_idx], a_end[v_idx] = u_hi, v_lo
        b_end[u_idx], b_end[v_idx] = u_lo, v_hi
        return origin, a_end, b_end

    port1_name, port2_name = f"{name_prefix}1", f"{name_prefix}2"
    try:
        for face, port_name in ((hi_face, port1_name), (lo_face, port2_name)):
            origin, a_end, b_end = _lattice_points(face)
            hfss.create_floquet_port(
                assignment=face, modes=n_modes, name=port_name,
                reporter_filter=True, deembed_distance=0,
                lattice_origin=origin, lattice_a_end=a_end, lattice_b_end=b_end,
            )
        log.info("Floquet ports '%s'/'%s' assigned on +/-%s faces, %d modes each",
                 port1_name, port2_name, propagation_axis, n_modes)
    except Exception as exc:
        log.error("Failed to assign Floquet ports on '%s': %s", air_box_name, exc)
        raise
    return port1_name, port2_name


def assign_periodic_lattice_pairs(hfss, air_box_name: str) -> list[str]:
    """Assign periodic (lattice-pair) boundary conditions to an air box's
    lateral faces via Hfss.auto_assign_lattice_pairs() -- the real PyAEDT
    1.1.0 method (confirmed this session). An earlier version of this
    function called hfss.assign_master_slave(...), which does not exist on
    this class (the "master/slave" terminology was renamed to "lattice
    pair"); that call would have raised AttributeError immediately.

    auto_assign_lattice_pairs auto-detects the periodic face pairs from the
    object's geometry (XY coordinate plane by default) -- simpler and less
    error-prone than manually identifying and pairing individual faces.
    """
    try:
        names = hfss.auto_assign_lattice_pairs(assignment=air_box_name)
        log.info("Periodic lattice-pair BCs assigned on '%s': %s", air_box_name, names)
        return names
    except Exception as exc:
        log.error("Failed to assign periodic lattice-pair BC on '%s': %s", air_box_name, exc)
        raise


# auto_assign_periodic_from_bounding_box() removed -- it duplicated, less
# reliably, what assign_periodic_lattice_pairs() already does by calling
# PyAEDT's own Hfss.auto_assign_lattice_pairs() directly. It also called the
# now-removed assign_periodic_master_slave(), which itself called a
# nonexistent hfss.assign_master_slave() method -- this function could never
# have actually run successfully against the installed PyAEDT 1.1.0 API.
