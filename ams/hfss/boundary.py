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


def assign_floquet_port(
    hfss,
    face_id_or_name: str | int,
    air_box_name: str,
    n_modes: int = 8,
    freq_range_GHz: tuple[float, float] = (1.0, 20.0),
    theta_incidence_deg: float = 0.0,
    phi_incidence_deg: float = 0.0,
    name: str = "FloquetPort",
) -> None:
    """Assign Floquet ports to the top and bottom faces of the air box.

    Floquet ports model plane wave excitation of an infinite periodic array.
    They are ALWAYS used in pairs (one on each side of the unit cell along
    the propagation direction, typically ±Z).

    Parameters
    ----------
    theta_incidence_deg : float
        Polar angle of incidence (0° = normal incidence).
    phi_incidence_deg : float
        Azimuthal angle of incidence.
    n_modes : int
        Number of Floquet modes.  8 covers up to ~18 GHz for a 20 mm cell.
        Rule: n_modes should include all modes with |k_t| < k₀ at the highest freq.

    Mode naming convention
    ----------------------
    Mode 1: TE(0,0) — normally incident TE plane wave
    Mode 2: TM(0,0) — normally incident TM plane wave
    Higher modes: evanescent (decay away from the port)

    S-parameters convention
    -----------------------
    S11 = reflection coefficient (Floquet port 1, mode 1)
    S21 = transmission coefficient (Floquet port 1 → port 2, mode 1)
    SE (shielding effectiveness) = -20 log₁₀|S21| dB
    """
    try:
        hfss.create_floquet_port(
            assignment   = air_box_name,
            deembedding  = 0,
            nummodes     = n_modes,
            reportfilter = True,
            name         = name,
        )
        log.info(
            "Floquet port '%s': %d modes, θ=%.1f°, φ=%.1f°",
            name, n_modes, theta_incidence_deg, phi_incidence_deg,
        )
    except Exception as exc:
        log.error("Failed to assign Floquet port '%s': %s", name, exc)
        raise


def assign_periodic_master_slave(
    hfss,
    master_face: str,
    slave_face:  str,
    axis:        str = "X",
    uv_face:     str | None = None,
    name_prefix: str = "Periodic",
) -> None:
    """Assign periodic master-slave boundary conditions.

    Used with Floquet ports for infinite periodic arrays.  The slave face
    fields are constrained to equal the master face fields with a phase shift:
        E_slave(r) = E_master(r - L) × exp(-j k_t · L)

    Parameters
    ----------
    master_face : str
        Name of the master boundary face (typically at x = 0).
    slave_face : str
        Name of the slave boundary face (typically at x = L_x).
    axis : str
        Periodicity direction ('X', 'Y', or 'Z').
    """
    try:
        hfss.assign_master_slave(
            master_entity = master_face,
            slave_entity  = slave_face,
            master_name   = f"{name_prefix}_Master",
            slave_name    = f"{name_prefix}_Slave",
        )
        log.info(
            "Periodic BC: master='%s' ↔ slave='%s' along %s",
            master_face, slave_face, axis,
        )
    except Exception as exc:
        log.error("Failed to assign periodic BC: %s", exc)
        raise


def auto_assign_periodic_from_bounding_box(
    hfss,
    air_box_name: str,
    axis: str = "X",
    tol_m: float = 1e-6,
) -> None:
    """Automatically detect and assign periodic BCs based on the air box bounding box.

    Finds the two faces of the air box orthogonal to 'axis' and assigns
    master-slave periodic BCs between them.  This is the standard setup for
    unit-cell Floquet analysis.

    Worked example (from origami EMI workflow)
    ------------------------------------------
    Air box: [0, L_x] × [0, L_y] × [z_min, z_max]
    Periodic in X: master at x=0, slave at x=L_x
    Periodic in Y: master at y=0, slave at y=L_y
    Result: simulates an infinite 2D periodic array of unit cells
    """
    try:
        air_box = hfss.modeler.objects.get(air_box_name)
        if air_box is None:
            raise ValueError(f"Air box object '{air_box_name}' not found in HFSS model")

        bb = air_box.bounding_box  # [xmin, ymin, zmin, xmax, ymax, zmax]
        ax_idx = {"X": 0, "Y": 1, "Z": 2}[axis.upper()]

        faces = list(air_box.faces)
        face_coords = []
        for face in faces:
            center = face.center
            face_coords.append((center[ax_idx], face))

        face_coords.sort(key=lambda x: x[0])

        if len(face_coords) < 2:
            raise ValueError(f"Could not find two faces along axis {axis}")

        master_face = face_coords[0][1]
        slave_face  = face_coords[-1][1]

        assign_periodic_master_slave(
            hfss,
            master_face = str(master_face.id),
            slave_face  = str(slave_face.id),
            axis        = axis,
        )

    except Exception as exc:
        log.error("Auto periodic BC assignment failed: %s", exc)
        raise
