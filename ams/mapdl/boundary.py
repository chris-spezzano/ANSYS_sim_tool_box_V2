"""
MAPDL Boundary Conditions — comprehensive BC assignment.

Supported condition types
--------------------------

Kinematic (Dirichlet) BCs — prescribed displacement or rotation
---------------------------------------------------------------
  displacement  : prescribe UX, UY, UZ (or ALL) to a value
  rotation      : prescribe ROTX, ROTY, ROTZ (for beam/shell nodes)
  symmetry      : apply symmetry plane constraints (UX=0 on X-plane, etc.)
  antisymmetry  : anti-symmetry plane constraints (UY=UZ=ROTX=ROTZ=0 on X-plane)

Dynamic (Neumann) BCs — prescribed force, traction, pressure
------------------------------------------------------------
  force         : concentrated nodal force
  moment        : concentrated nodal moment (beam/shell)
  pressure      : surface traction (force per area)
  body_force    : gravitational or inertial acceleration
  thermal_load  : temperature field (coupling MAPDL temp with structural)

Periodic BCs — periodic unit cell analysis
------------------------------------------
  periodic      : couple DOFs on opposite faces (master-slave via CP command)

Robin / mixed BCs — elastic foundation, contact-like springs
------------------------------------------------------------
  elastic_support : foundation stiffness (spring per unit area)
  convection      : thermal convection film coefficient

Mathematical basis
------------------

Strong form of elasticity (Cauchy's equation of motion):
    ∇·σ + b = ρ ü    in Ω  (body force + inertia)
    σ·n = t           on Γ_N  (Neumann BC — traction)
    u = ū             on Γ_D  (Dirichlet BC — prescribed displacement)

where:
  σ = Cauchy stress tensor (3×3 symmetric)
  b = body force per unit volume (N/m³)
  ρ = density (kg/m³)
  ü = nodal acceleration (m/s²)
  n = outward normal to the surface
  t = surface traction vector (N/m²)
  u = displacement (m)

Robin (mixed) BC — elastic foundation:
    σ·n = -k_s · u    on Γ_R
where k_s is the foundation stiffness (N/m³).

Periodic BC:
    u(x + L) = u(x)   for all x on the periodic boundary
Implemented via MAPDL constraint equations: CP,nset,DOF,node1,coeff1,node2,coeff2...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def apply_boundary_conditions(mapdl, cfg: dict) -> None:
    """Apply all boundary conditions defined in the config dict.

    Parameters
    ----------
    mapdl : PyMAPDL instance (must be in /PREP7)
    cfg : dict
        The 'bcs' section of the master config, containing:
          constraints: list of kinematic BC dicts
          loads:       list of load BC dicts
          periodic:    optional periodic BC config
          contact:     optional contact definition
    """
    mapdl.prep7()

    constraints = cfg.get("constraints", [])
    loads       = cfg.get("loads", [])
    periodic    = cfg.get("periodic")

    for bc in constraints:
        _apply_kinematic(mapdl, bc)

    for bc in loads:
        _apply_load(mapdl, bc)

    if periodic:
        _apply_periodic(mapdl, periodic)

    mapdl.nsel("ALL")
    log.info("All boundary conditions applied")


# ─────────────────────────────────────────────────────────────────────────────
# Advanced public functions (called directly from notebooks)
# ─────────────────────────────────────────────────────────────────────────────

def apply_dirichlet(
    mapdl,
    location: str,
    axis: str,
    coord: float,
    dofs: list[str],
    value: float = 0.0,
    tol: float | None = None,
) -> None:
    """Apply a Dirichlet (displacement/rotation) constraint on a face.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    location : str
        'face' | 'edge' | 'node_set'
    axis : str
        Axis along which to select the face: 'X' | 'Y' | 'Z'
    coord : float
        Coordinate value of the face (m).
    dofs : list[str]
        DOFs to constrain, e.g., ['UX', 'UY', 'UZ'] or ['ALL'].
    value : float
        Prescribed value (m for displacement, rad for rotation).
        Use 0.0 for fixed constraints.
    tol : float | None
        Selection tolerance (m).  Defaults to 1e-6 × domain size.

    Notes
    -----
    Dirichlet BCs reduce the system size by eliminating prescribed DOFs:
    Partition K into free (f) and constrained (c) sets:
        [K_ff  K_fc] [u_f]   [F_f - K_fc · u_c]
        [K_cf  K_cc] [u_c] = [F_c              ]
    Only the (ff) block is solved; constrained DOFs are known.
    """
    tol = tol or 1e-6

    axis_upper = axis.upper()
    mapdl.nsel("S", "LOC", axis_upper, coord - tol, coord + tol)

    for dof in dofs:
        mapdl.d("ALL", dof.upper(), value)

    n_constrained = mapdl.mesh.n_node
    log.info(
        "Dirichlet BC: %s=%s on %s=%.4g  (tol=%.2e, %d nodes)",
        dofs, value, axis_upper, coord, tol, n_constrained,
    )
    mapdl.nsel("ALL")


def apply_neumann_pressure(
    mapdl,
    location: str,
    axis: str,
    coord: float,
    pressure_Pa: float,
    tol: float | None = None,
) -> None:
    """Apply a pressure (Neumann) boundary condition on a face.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    location : str
        'face' (select by coordinate).
    axis : str
        'X' | 'Y' | 'Z' — outward normal direction.
    coord : float
        Coordinate of the face.
    pressure_Pa : float
        Pressure in Pa.  Positive = compressive (ANSYS convention);
        Negative = tensile (pulling away from face).

        Physical note: a tensile traction σ_far applied on the +X face
        requires pressure_Pa = -σ_far (compressive sign → negative = tensile).
    tol : float | None
        Selection tolerance.

    Mathematical basis
    ------------------
    The weak form contribution from the Neumann BC is:
        ∫_{Γ_N} δu · t dA
    where t = -p · n is the traction vector (n = outward normal).
    ANSYS implements this as a face load via SFE command.
    """
    tol = tol or 1e-6

    axis_upper = axis.upper()
    ldir = {"X": 1, "Y": 2, "Z": 3}.get(axis_upper, 2)

    # Select faces at the target coordinate
    mapdl.nsel("S", "LOC", axis_upper, coord - tol, coord + tol)
    mapdl.esln("S", 0)      # select elements attached to selected nodes
    mapdl.nsle("S")         # reselect only the boundary-face nodes

    # Apply surface pressure (SF command: surface load on elements)
    # PRES = face 1 pressure; face numbering: 1=+X, 2=+Y, etc. (element-dependent)
    mapdl.sf("ALL", "PRES", pressure_Pa)

    log.info(
        "Neumann pressure %.3e Pa on face %s=%.4g",
        pressure_Pa, axis_upper, coord,
    )
    mapdl.nsel("ALL")


def apply_force(
    mapdl,
    node_id: int,
    dof: str,
    value_N: float,
) -> None:
    """Apply a concentrated force or moment to a single node.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    node_id : int
        MAPDL node number (1-based).
    dof : str
        'FX' | 'FY' | 'FZ' (force, N) | 'MX' | 'MY' | 'MZ' (moment, N·m)
    value_N : float
        Load magnitude.

    Notes
    -----
    Concentrated forces are equivalent to a Dirac delta traction:
        t(x) = F · δ(x - x_node)
    This creates a stress singularity at the application point.
    For structural results far from the point: correct.
    At the application node itself: mesh-dependent (use distributed load for accuracy).
    """
    mapdl.f(node_id, dof.upper(), value_N)
    log.info("Force %s = %.3e at node %d", dof.upper(), value_N, node_id)


def apply_body_force(
    mapdl,
    g_x: float = 0.0,
    g_y: float = -9.81,
    g_z: float = 0.0,
) -> None:
    """Apply gravitational body force.

    Parameters
    ----------
    g_x, g_y, g_z : float
        Gravitational acceleration components (m/s²).
        Default: standard gravity in -Y direction.

    Notes
    -----
    Body force enters the weak form as:
        ∫_Ω δu · ρ·b dV
    where b = [g_x, g_y, g_z] is the body force per unit mass.
    MAPDL implements this via ACEL (acceleration loads).
    Note: ACEL takes the ACCELERATION of the reference frame, not the
    gravity vector.  To simulate gravity in -Y: ACEL,0,9.81,0 (positive Y accel).
    """
    mapdl.acel(abs(g_x), abs(g_y), abs(g_z))
    log.info(
        "Body force applied: [%.3g, %.3g, %.3g] m/s²", g_x, g_y, g_z,
    )


def apply_symmetry(
    mapdl,
    plane: str,
    coord: float = 0.0,
    tol: float | None = None,
) -> None:
    """Apply symmetry plane boundary conditions.

    For a symmetry plane normal to the X-axis:
        UX = 0, ROTY = 0, ROTZ = 0  (for shells/beams)
        UX = 0 alone is sufficient for 3D solid elements (no rotational DOFs)

    Parameters
    ----------
    plane : str
        'XY' | 'YZ' | 'XZ' — the symmetry plane.
        'XY' plane normal to Z → constrains UZ.
        'YZ' plane normal to X → constrains UX.
        'XZ' plane normal to Y → constrains UY.
    coord : float
        Coordinate value of the symmetry plane.
    tol : float | None
        Selection tolerance.
    """
    tol = tol or 1e-6
    plane_upper = plane.upper()

    # Map plane to the constrained DOF and selection axis
    plane_map = {
        "YZ": ("X", "UX"),
        "XZ": ("Y", "UY"),
        "XY": ("Z", "UZ"),
    }
    if plane_upper not in plane_map:
        raise ValueError(f"Unknown plane '{plane}'.  Use 'YZ', 'XZ', or 'XY'.")

    sel_axis, dof = plane_map[plane_upper]
    mapdl.nsel("S", "LOC", sel_axis, coord - tol, coord + tol)
    mapdl.d("ALL", dof, 0.0)

    n_sym = mapdl.mesh.n_node
    log.info(
        "Symmetry BC: %s = 0 on %s-plane at %s=%.4g (%d nodes)",
        dof, plane_upper, sel_axis, coord, n_sym,
    )
    mapdl.nsel("ALL")


def apply_periodic(
    mapdl,
    axis: str,
    lo_coord: float,
    hi_coord: float,
    dofs: list[str],
    tol: float | None = None,
) -> None:
    """Apply periodic boundary conditions using constraint equations (CP).

    Periodic BCs enforce:
        u(x + L) = u(x)  (master nodes on hi-face = slave nodes on lo-face)

    This is used for unit-cell analysis (e.g., RVE homogenization,
    periodic metamaterials) where the field repeats with period L.

    MAPDL implementation
    --------------------
    The CP (coupled DOF set) command links two nodes' DOFs:
        CP, NSET, DOF, NODE1, NODE2, ...
    All nodes in the set share the same DOF value.
    For periodic BCs: pair each lo-face node with its matching hi-face node.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    axis : str
        'X' | 'Y' | 'Z' — the direction of periodicity.
    lo_coord, hi_coord : float
        Coordinates of the two periodic faces.
    dofs : list[str]
        DOFs to couple, e.g., ['UX', 'UY', 'UZ'].
    tol : float | None
        Coordinate tolerance for node pairing.
    """
    tol = tol or 1e-6
    ax  = axis.upper()

    # Select nodes on the lo face
    mapdl.nsel("S", "LOC", ax, lo_coord - tol, lo_coord + tol)
    lo_nodes = list(mapdl.mesh.nnum)

    # Select nodes on the hi face
    mapdl.nsel("S", "LOC", ax, hi_coord - tol, hi_coord + tol)
    hi_nodes = list(mapdl.mesh.nnum)

    mapdl.nsel("ALL")

    if len(lo_nodes) != len(hi_nodes):
        raise ValueError(
            f"Periodic BC mismatch: {len(lo_nodes)} nodes on lo-face vs "
            f"{len(hi_nodes)} on hi-face.  Periodic BCs require matching mesh on both faces."
        )

    # Get node coordinates and sort both sets by their non-periodic coordinates
    nodes_xyz = mapdl.mesh.nodes
    nnum_all  = list(mapdl.mesh.nnum)
    id_to_idx = {int(n): i for i, n in enumerate(nnum_all)}

    perp_axes = [a for a in ["X", "Y", "Z"] if a != ax]

    def perp_key(nid: int) -> tuple:
        idx = id_to_idx[nid]
        coord = nodes_xyz[idx]
        p = {"X": 0, "Y": 1, "Z": 2}
        return tuple(round(coord[p[a]], 9) for a in perp_axes)

    lo_sorted = sorted(lo_nodes, key=perp_key)
    hi_sorted = sorted(hi_nodes, key=perp_key)

    # Create coupled DOF sets for each pair
    for dof in dofs:
        for i, (n_lo, n_hi) in enumerate(zip(lo_sorted, hi_sorted)):
            nset = i + 1
            mapdl.cp(nset, dof.upper(), n_lo, n_hi)

    log.info(
        "Periodic BCs: %d node pairs coupled on %s (%s) for DOFs %s",
        len(lo_sorted), ax, f"{lo_coord:.4g} ↔ {hi_coord:.4g}", dofs,
    )


def apply_elastic_support(
    mapdl,
    axis: str,
    coord: float,
    stiffness_N_m3: float,
    tol: float | None = None,
) -> None:
    """Apply an elastic foundation (Winkler spring) to a face.

    Models a distributed spring support — common for soil-structure
    interaction, gasket contact, or soft tissue support.

    Parameters
    ----------
    stiffness_N_m3 : float
        Foundation modulus k_s (N/m³ = Pa/m).  Typical values:
          - Soft soil:     1e5 N/m³
          - Hard soil:     1e7 N/m³
          - Concrete slab: 1e8 N/m³

    Mathematical basis (Robin BC)
    -----------------------------
    The distributed spring contributes to the weak form as:
        ∫_{Γ_R} k_s · δu · u dA
    This adds terms to the global stiffness matrix along the surface.
    MAPDL implements this via SURF154 (3D) or SURF153 (2D) overlay elements
    with EF (elastic foundation) real constants.
    """
    tol = tol or 1e-6
    ax  = axis.upper()

    # Select faces at the support coordinate
    mapdl.nsel("S", "LOC", ax, coord - tol, coord + tol)
    mapdl.esln("S", 0)

    # Add SURF154 overlay elements
    mapdl.et(99, "SURF154")
    mapdl.r(99, stiffness_N_m3)
    mapdl.esurf()

    log.info(
        "Elastic support (k_s=%.3e N/m³) on %s=%.4g", stiffness_N_m3, ax, coord
    )
    mapdl.nsel("ALL")
    mapdl.esel("ALL")


# ─────────────────────────────────────────────────────────────────────────────
# Internal dispatch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _apply_kinematic(mapdl, bc: dict) -> None:
    """Dispatch a kinematic constraint dict to the appropriate function."""
    bc_type = bc.get("type", "").lower()
    axis    = bc.get("axis", "X")
    side    = bc.get("side", "min")
    tol     = bc.get("tol", 1e-6)
    value   = bc.get("value", 0.0)
    dofs    = bc.get("dofs", ["UX", "UY", "UZ"])

    if bc_type == "displacement":
        # Compute coordinate from mesh bounds
        coord = _get_coord(mapdl, axis, side)
        apply_dirichlet(mapdl, "face", axis, coord, dofs, value, tol)

    elif bc_type == "symmetry":
        plane = bc.get("plane", "YZ")
        coord = bc.get("coord", 0.0)
        apply_symmetry(mapdl, plane, coord, tol)

    elif bc_type == "fixed":
        coord = _get_coord(mapdl, axis, side)
        apply_dirichlet(mapdl, "face", axis, coord, ["ALL"], 0.0, tol)

    else:
        log.warning("Unknown kinematic BC type: '%s' — skipping", bc_type)


def _apply_load(mapdl, bc: dict) -> None:
    """Dispatch a load BC dict to the appropriate function."""
    bc_type = bc.get("type", "").lower()
    axis    = bc.get("axis", "X")
    side    = bc.get("side", "max")
    tol     = bc.get("tol", 1e-6)

    if bc_type == "pressure":
        coord = _get_coord(mapdl, axis, side)
        apply_neumann_pressure(mapdl, "face", axis, coord, bc.get("value_Pa", 0.0), tol)

    elif bc_type == "force":
        apply_force(mapdl, bc["node_id"], bc.get("dof", "FX"), bc.get("value_N", 0.0))

    elif bc_type == "gravity":
        apply_body_force(
            bc.get("gx", 0.0), bc.get("gy", -9.81), bc.get("gz", 0.0)
        )

    elif bc_type == "elastic_support":
        coord = _get_coord(mapdl, axis, side)
        apply_elastic_support(mapdl, axis, coord, bc.get("stiffness_N_m3", 1e6), tol)

    else:
        log.warning("Unknown load BC type: '%s' — skipping", bc_type)


def _apply_periodic(mapdl, cfg: dict) -> None:
    """Apply periodic BCs from the config block."""
    apply_periodic(
        mapdl,
        axis      = cfg.get("axis", "X"),
        lo_coord  = cfg["lo_coord"],
        hi_coord  = cfg["hi_coord"],
        dofs      = cfg.get("dofs", ["UX", "UY", "UZ"]),
        tol       = cfg.get("tol", 1e-6),
    )


def _get_coord(mapdl, axis: str, side: str) -> float:
    """Return the min or max coordinate of the mesh along the given axis."""
    nodes = mapdl.mesh.nodes
    ax_map = {"X": 0, "Y": 1, "Z": 2}
    col = ax_map.get(axis.upper(), 0)
    coords = nodes[:, col]
    return float(coords.min()) if side.lower() == "min" else float(coords.max())
