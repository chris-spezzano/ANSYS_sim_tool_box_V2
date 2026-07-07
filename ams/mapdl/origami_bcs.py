"""
Origami Boundary Conditions — waterbomb fold simulation in MAPDL SHELL181.

Waterbomb geometry recap
------------------------
The waterbomb origami is a square sheet with 8 triangular panels arranged in
a pinwheel pattern.  From the flat state, it folds into a dome-like shape.

Crease-line topology (for a plate of side L centred at (cx, cy)):
  - Vertical crease:     x = cx   (runs full height)
  - Horizontal crease:   y = cy   (runs full width)
  - +45° diagonal crease: y − cy =  (x − cx)   → y = x − cx + cy
  - −45° diagonal crease: y − cy = −(x − cx)   → y = −x + cx + cy

Fold mechanics
--------------
Two BC strategies are provided:

A) Displacement-driven (recommended for automated sweeps)
   -------------------------------------------------------
   1. Pin the centre patch (UX=UY=UZ=0) — removes rigid-body translation.
   2. Apply UZ displacement to the 4 outer corner nodes — drives the fold.
   3. Apply anti-symmetry / symmetry on the crease planes to keep the fold
      shape clean.  Optional: reduces the model to 1/4 with two symmetry BCs.

   Fold angle ↔ corner displacement mapping:
       UZ_corner = (L/2) × sin(θ)
   where θ is the target fold half-angle (angle between panel and flat plane).

B) Rotation-driven (more physically meaningful, requires SHELL181)
   ----------------------------------------------------------------
   1. Pin the centre patch (UX=UY=UZ=0).
   2. For each crease line, prescribe a rotation perpendicular to the crease:
      - Vertical crease:     constrain ROTY = ±fold_angle_rad
      - Horizontal crease:   constrain ROTX = ±fold_angle_rad
      - Diagonal creases:    constrain rotation about the crease direction
   3. Mountain vs valley folds are distinguished by sign.

   Note: This approach is more numerically challenging.  Use large-deformation
   substeps (nsubst ≥ 200) and NLGEOM=ON.

Named components (from nTopology export — preferred)
------------------------------------------------------
If the .ntop file exports named components (CMBLOCK records in the CDB),
select them directly:
    mapdl.cmsel("S", "CREASE_VERT")
    mapdl.cmsel("A", "CREASE_HORIZ")

Coordinate-based fallback (always works)
-----------------------------------------
If named components are absent, use the coordinate selection functions
defined here.  They compute crease membership in NumPy and issue individual
NSEL,A commands — slower for large meshes but reliable.
"""

from __future__ import annotations

import logging
import math
import numpy as np

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def apply_waterbomb_fold_bcs(mapdl, cfg: dict) -> None:
    """Apply all boundary conditions for a waterbomb fold simulation.

    Reads the ``bcs.origami_fold`` section of the config dict.

    YAML schema
    -----------
    .. code-block:: yaml

        bcs:
          origami_fold:
            strategy: "displacement"   # displacement | rotation

            # Plate geometry (must match nTop geometry)
            plate_length_mm:  70.0     # side length (square plate)
            plate_center_x_mm: 35.0   # default = plate_length/2
            plate_center_y_mm: 35.0

            # Fold target
            fold_uz_mm:        15.0    # corner Z-displacement (displacement strategy)
            fold_angle_deg:    30.0    # fold half-angle (rotation strategy)

            # BC style
            pin_center_radius_mm: 2.0  # radius of centre patch to fix
            use_symmetry: false        # exploit 4-fold symmetry (reduces model to 1/4)

            # Crease width tolerance for coordinate-based selection
            crease_tol_mm: 0.3        # half-width of crease selection band (mm)

            # Named components exported by nTopology (leave null to use coords)
            component_names:
              center_patch:  "CENTER_PATCH"   # or null
              outer_corners: "OUTER_CORNERS"  # or null
              crease_vert:   "CREASE_VERT"    # or null
              crease_horiz:  "CREASE_HORIZ"   # or null
              crease_diag_p: "CREASE_DIAG_P"  # or null
              crease_diag_n: "CREASE_DIAG_N"  # or null

    Parameters
    ----------
    mapdl : PyMAPDL instance (must be in /PREP7)
    cfg : dict
        The full pipeline config dict.
    """
    origami_cfg = cfg.get("bcs", {}).get("origami_fold", {})
    if not origami_cfg:
        raise ValueError(
            "Config missing 'bcs.origami_fold' section.\n"
            "Add the origami_fold block — see docstring for schema."
        )

    mapdl.prep7()

    strategy = origami_cfg.get("strategy", "displacement").lower()

    L   = float(origami_cfg.get("plate_length_mm", 70.0)) * 1e-3  # → m
    cx  = float(origami_cfg.get("plate_center_x_mm", L * 500)) * 1e-3
    cy  = float(origami_cfg.get("plate_center_y_mm", L * 500)) * 1e-3
    # default centre = L/2 if not set explicitly
    if "plate_center_x_mm" not in origami_cfg:
        cx = L / 2.0
    if "plate_center_y_mm" not in origami_cfg:
        cy = L / 2.0

    crease_tol = float(origami_cfg.get("crease_tol_mm", 0.3)) * 1e-3
    pin_r      = float(origami_cfg.get("pin_center_radius_mm", 2.0)) * 1e-3
    comps      = origami_cfg.get("component_names", {}) or {}

    # 1. Pin the centre patch
    _pin_center(mapdl, cx, cy, pin_r, comps.get("center_patch"))

    if strategy == "displacement":
        uz_m = float(origami_cfg.get("fold_uz_mm", 15.0)) * 1e-3
        _apply_corner_displacement(mapdl, L, cx, cy, uz_m, comps.get("outer_corners"))
    elif strategy == "rotation":
        angle_rad = math.radians(float(origami_cfg.get("fold_angle_deg", 30.0)))
        _apply_crease_rotations(
            mapdl, cx, cy, angle_rad, crease_tol, comps,
        )
    else:
        raise ValueError(
            f"Unknown origami_fold.strategy '{strategy}'. "
            "Use 'displacement' or 'rotation'."
        )

    # 2. Optional 4-fold symmetry reduction
    if origami_cfg.get("use_symmetry", False):
        _apply_waterbomb_symmetry(mapdl, cx, cy)

    mapdl.nsel("ALL")
    log.info("Waterbomb BCs applied: strategy=%s, L=%.1f mm, cx=%.1f, cy=%.1f",
             strategy, L * 1e3, cx * 1e3, cy * 1e3)


# ─────────────────────────────────────────────────────────────────────────────
# Centre-pin BC
# ─────────────────────────────────────────────────────────────────────────────

def _pin_center(
    mapdl,
    cx: float,
    cy: float,
    radius_m: float,
    component_name: str | None = None,
) -> None:
    """Fix UX=UY=UZ=0 at the plate centre to prevent rigid-body translation.

    For SHELL181 the rotational DOFs are left free so the centre can rotate
    as part of the fold kinematics.

    Parameters
    ----------
    cx, cy : float
        Centre coordinates in metres.
    radius_m : float
        Radius of the centre patch to pin (m).  All nodes within this circle
        in the XY plane receive UX=UY=UZ=0.
    component_name : str | None
        If set, selects the named component instead of computing by coordinate.
    """
    if component_name:
        try:
            mapdl.cmsel("S", component_name)
            n_pinned = mapdl.mesh.n_node
            log.debug("Centre pin via component '%s': %d nodes", component_name, n_pinned)
        except Exception:
            log.warning("Component '%s' not found, falling back to coordinate selection", component_name)
            component_name = None

    if not component_name:
        # Select nodes within radius_m of (cx, cy) in XY plane
        nodes_xyz = mapdl.mesh.nodes
        nnum      = mapdl.mesh.nnum
        if len(nodes_xyz) == 0:
            raise RuntimeError("No nodes found in mesh — run geometry import first.")

        r2 = (nodes_xyz[:, 0] - cx) ** 2 + (nodes_xyz[:, 1] - cy) ** 2
        centre_mask = r2 <= radius_m ** 2
        centre_nodes = nnum[centre_mask]

        if len(centre_nodes) == 0:
            raise RuntimeError(
                f"No nodes found within r={radius_m*1e3:.2f} mm of centre "
                f"({cx*1e3:.1f}, {cy*1e3:.1f}) mm.  "
                "Increase pin_center_radius_mm or verify plate_center_x/y_mm."
            )

        mapdl.nsel("NONE")
        for n in centre_nodes:
            mapdl.nsel("A", "NODE", "", int(n))
        n_pinned = len(centre_nodes)
        log.debug("Centre pin via coordinates: %d nodes, r=%.2f mm", n_pinned, radius_m * 1e3)

    mapdl.d("ALL", "UX", 0.0)
    mapdl.d("ALL", "UY", 0.0)
    mapdl.d("ALL", "UZ", 0.0)

    log.info("Centre pinned (UX=UY=UZ=0): %d nodes, r=%.2f mm", n_pinned, radius_m * 1e3)
    print(f"  BCs: centre patch pinned ({n_pinned} nodes, r={radius_m*1e3:.1f} mm)")
    mapdl.nsel("ALL")


# ─────────────────────────────────────────────────────────────────────────────
# Displacement-driven fold (Strategy A)
# ─────────────────────────────────────────────────────────────────────────────

def _apply_corner_displacement(
    mapdl,
    L: float,
    cx: float,
    cy: float,
    uz_m: float,
    component_name: str | None = None,
) -> None:
    """Apply waterbomb kinematics via displacement BCs.

    Correct waterbomb base fold requires THREE sets of constraints:

    1. Centre patch: UX=UY=UZ=0  (handled by _pin_center before this call)
    2. Edge midpoints (cardinal crease terminations): UZ=0
       - These are the 4 points at (+L/2,0), (-L/2,0), (0,+L/2), (0,-L/2)
       - Constraining UZ=0 here enforces the mountain fold at cardinal creases
       - The sheet cannot bow upward uniformly; deformation must concentrate
         at the hinge lines
    3. Corner regions: UZ=+uz_m  (valley fold — corners rise)

    This creates the characteristic waterbomb tent: 4 triangular panels fold
    up about the diagonal valley creases, with the cardinal lines as mountains.

    Parameters
    ----------
    L : float
        Plate side length (m).
    cx, cy : float
        Plate centre (m).
    uz_m : float
        Target Z-displacement at the corners (m, positive = upward).
    component_name : str | None
        Named nTop component for outer-corner nodes, if available.
    """
    nodes_xyz = mapdl.mesh.nodes
    nnum      = mapdl.mesh.nnum
    corner_tol     = L * 0.05    # 5% of side — generous corner zone
    midpoint_tol   = L * 0.08    # 8% of side — generous edge midpoint zone

    # ── 2. Edge midpoints: UZ = 0 (mountain fold constraint) ────────────────
    # The 4 cardinal edge midpoints: (±L/2, 0) and (0, ±L/2)
    edge_midpoints = [
        (cx + L / 2, cy),
        (cx - L / 2, cy),
        (cx,          cy + L / 2),
        (cx,          cy - L / 2),
    ]
    edge_mask = np.zeros(len(nnum), dtype=bool)
    for (xm, ym) in edge_midpoints:
        r2 = (nodes_xyz[:, 0] - xm) ** 2 + (nodes_xyz[:, 1] - ym) ** 2
        edge_mask |= r2 <= midpoint_tol ** 2

    edge_nodes = nnum[edge_mask]
    if len(edge_nodes) > 0:
        mapdl.nsel("NONE")
        for n in edge_nodes:
            mapdl.nsel("A", "NODE", "", int(n))
        mapdl.d("ALL", "UZ", 0.0)
        print(f"  BCs: edge midpoints UZ=0 (mountain fold constraint, {len(edge_nodes)} nodes)")
    else:
        log.warning("No edge midpoint nodes found — skipping mountain fold constraint")

    mapdl.nsel("ALL")

    # ── 3. Corners: UZ = uz_m (valley fold — corners rise) ───────────────────
    if component_name:
        try:
            mapdl.cmsel("S", component_name)
            n_corners = mapdl.mesh.n_node
            log.debug("Corners via component '%s': %d nodes", component_name, n_corners)
        except Exception:
            log.warning("Component '%s' not found, falling back to coordinate selection", component_name)
            component_name = None

    if not component_name:
        corners = [
            (cx - L / 2, cy - L / 2),
            (cx + L / 2, cy - L / 2),
            (cx - L / 2, cy + L / 2),
            (cx + L / 2, cy + L / 2),
        ]
        mask = np.zeros(len(nnum), dtype=bool)
        for (xc, yc) in corners:
            r2 = (nodes_xyz[:, 0] - xc) ** 2 + (nodes_xyz[:, 1] - yc) ** 2
            mask |= r2 <= corner_tol ** 2

        # Exclude any nodes already constrained as edge midpoints
        mask &= ~edge_mask

        corner_nodes = nnum[mask]
        if len(corner_nodes) == 0:
            raise RuntimeError(
                "No corner nodes found.  Check plate_length_mm and plate_center_x/y_mm."
            )

        mapdl.nsel("NONE")
        for n in corner_nodes:
            mapdl.nsel("A", "NODE", "", int(n))
        n_corners = len(corner_nodes)

    mapdl.d("ALL", "UZ", uz_m)

    fold_angle_deg = math.degrees(math.asin(min(abs(uz_m) / (L / 2), 1.0)))
    log.info(
        "Corner displacement UZ=%.3f mm applied to %d nodes "
        "(fold half-angle %.1f°)",
        uz_m * 1e3, n_corners, fold_angle_deg,
    )
    print(f"  BCs: corner fold UZ={uz_m*1e3:.1f} mm (~{fold_angle_deg:.1f} deg half-angle), {n_corners} nodes")
    mapdl.nsel("ALL")


# ─────────────────────────────────────────────────────────────────────────────
# Rotation-driven fold (Strategy B)
# ─────────────────────────────────────────────────────────────────────────────

def _apply_crease_rotations(
    mapdl,
    cx: float,
    cy: float,
    fold_angle_rad: float,
    crease_tol_m: float,
    comps: dict[str, str | None],
) -> None:
    """Apply prescribed rotations at each crease line (SHELL181 strategy).

    Mountain vs valley designation follows the standard waterbomb convention:
      - Horizontal and vertical creases: ROTY / ROTX = +fold_angle (valley fold up)
      - Diagonal creases:                rotation = −fold_angle (mountain fold down)

    Parameters
    ----------
    cx, cy : float
        Plate centre coordinates (m).
    fold_angle_rad : float
        Target fold half-angle in radians.
    crease_tol_m : float
        Half-band width for coordinate-based crease node selection (m).
    comps : dict
        Named components from nTop — keys: crease_vert, crease_horiz,
        crease_diag_p, crease_diag_n.
    """
    _apply_single_crease_rotation(
        mapdl, crease_type="vertical",
        cx=cx, cy=cy, tol=crease_tol_m,
        dof="ROTY", angle=fold_angle_rad,
        component_name=comps.get("crease_vert"),
    )
    _apply_single_crease_rotation(
        mapdl, crease_type="horizontal",
        cx=cx, cy=cy, tol=crease_tol_m,
        dof="ROTX", angle=fold_angle_rad,
        component_name=comps.get("crease_horiz"),
    )
    _apply_single_crease_rotation(
        mapdl, crease_type="diag_p",
        cx=cx, cy=cy, tol=crease_tol_m,
        dof="ROTZ", angle=-fold_angle_rad,    # mountain fold
        component_name=comps.get("crease_diag_p"),
    )
    _apply_single_crease_rotation(
        mapdl, crease_type="diag_n",
        cx=cx, cy=cy, tol=crease_tol_m,
        dof="ROTZ", angle=-fold_angle_rad,    # mountain fold
        component_name=comps.get("crease_diag_n"),
    )


def _apply_single_crease_rotation(
    mapdl,
    crease_type: str,
    cx: float,
    cy: float,
    tol: float,
    dof: str,
    angle: float,
    component_name: str | None = None,
) -> None:
    """Select nodes on one crease line and apply a prescribed rotation."""
    if component_name:
        try:
            mapdl.cmsel("S", component_name)
            n_crease = mapdl.mesh.n_node
            log.debug("Crease %s via component '%s': %d nodes",
                      crease_type, component_name, n_crease)
        except Exception:
            log.warning("Component '%s' not found, using coordinate fallback", component_name)
            component_name = None

    if not component_name:
        nodes_xyz = mapdl.mesh.nodes
        nnum      = mapdl.mesh.nnum
        x = nodes_xyz[:, 0]
        y = nodes_xyz[:, 1]

        if crease_type == "vertical":
            mask = np.abs(x - cx) < tol
        elif crease_type == "horizontal":
            mask = np.abs(y - cy) < tol
        elif crease_type == "diag_p":      # +45°: y − cy = x − cx
            mask = np.abs((y - cy) - (x - cx)) < tol
        elif crease_type == "diag_n":      # −45°: y − cy = −(x − cx)
            mask = np.abs((y - cy) + (x - cx)) < tol
        else:
            raise ValueError(f"Unknown crease_type: {crease_type!r}")

        crease_nodes = nnum[mask]
        if len(crease_nodes) == 0:
            log.warning(
                "No nodes found on %s crease (tol=%.2f mm).  "
                "Increase crease_tol_mm.", crease_type, tol * 1e3
            )
            return

        mapdl.nsel("NONE")
        for n in crease_nodes:
            mapdl.nsel("A", "NODE", "", int(n))
        n_crease = len(crease_nodes)

    mapdl.d("ALL", dof.upper(), angle)
    log.info(
        "Crease %s: %s=%.3f rad (%.1f°), %d nodes",
        crease_type, dof.upper(), angle, math.degrees(angle), n_crease,
    )
    print(f"  BCs: {crease_type} crease — {dof}={math.degrees(angle):.1f}°  ({n_crease} nodes)")
    mapdl.nsel("ALL")


# ─────────────────────────────────────────────────────────────────────────────
# Optional 4-fold symmetry
# ─────────────────────────────────────────────────────────────────────────────

def _apply_waterbomb_symmetry(mapdl, cx: float, cy: float) -> None:
    """Apply 4-fold symmetry by constraining the crease planes.

    For a waterbomb exploiting XY/XZ symmetry, model only the +X +Y quadrant:
      - On the x = cx plane: constrain UX = 0  (symmetry normal to X)
      - On the y = cy plane: constrain UY = 0  (symmetry normal to Y)

    This reduces the model to 1/4 size.  Only valid when the fold and loads
    are symmetric about both crease axes.

    Warning: diagonal crease folds break this symmetry.  Use only when the
    simulation is a pure vertical/horizontal fold (not the full waterbomb).
    """
    tol = 1e-6
    # YZ-plane symmetry at x = cx: constrain UX
    mapdl.nsel("S", "LOC", "X", cx - tol, cx + tol)
    mapdl.d("ALL", "UX", 0.0)
    n_yz = mapdl.mesh.n_node

    # XZ-plane symmetry at y = cy: constrain UY
    mapdl.nsel("S", "LOC", "Y", cy - tol, cy + tol)
    mapdl.d("ALL", "UY", 0.0)
    n_xz = mapdl.mesh.n_node

    mapdl.nsel("ALL")
    log.info(
        "4-fold symmetry applied: UX=0 on x=%.3f m (%d nodes), "
        "UY=0 on y=%.3f m (%d nodes)",
        cx, n_yz, cy, n_xz,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Utility: identify crease node sets (useful for post-processing)
# ─────────────────────────────────────────────────────────────────────────────

def get_crease_node_sets(mapdl, cx: float, cy: float, crease_tol_m: float) -> dict[str, np.ndarray]:
    """Return a dict of node-number arrays for each crease type.

    Used for post-processing fold angles and strain localisation.

    Returns
    -------
    dict with keys: "vertical", "horizontal", "diag_p", "diag_n", "all_creases"
    """
    nodes_xyz = mapdl.mesh.nodes
    nnum      = mapdl.mesh.nnum
    x = nodes_xyz[:, 0]
    y = nodes_xyz[:, 1]
    tol = crease_tol_m

    sets = {
        "vertical":   nnum[np.abs(x - cx) < tol],
        "horizontal": nnum[np.abs(y - cy) < tol],
        "diag_p":     nnum[np.abs((y - cy) - (x - cx)) < tol],
        "diag_n":     nnum[np.abs((y - cy) + (x - cx)) < tol],
    }
    all_crease_mask = (
        (np.abs(x - cx) < tol) |
        (np.abs(y - cy) < tol) |
        (np.abs((y - cy) - (x - cx)) < tol) |
        (np.abs((y - cy) + (x - cx)) < tol)
    )
    sets["all_creases"] = nnum[all_crease_mask]

    for name, nodes in sets.items():
        log.debug("Crease set '%s': %d nodes", name, len(nodes))

    return sets


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: fold angle extraction (post-processing)
# ─────────────────────────────────────────────────────────────────────────────

def compute_fold_angles(mapdl, crease_node_sets: dict[str, np.ndarray]) -> dict[str, float]:
    """Compute the average fold angle at each crease line from MAPDL displacements.

    Must be called after the solve, inside a /POST1 session.

    Returns
    -------
    dict mapping crease name → mean fold half-angle (degrees).
    """
    angles: dict[str, float] = {}
    for name, nodes in crease_node_sets.items():
        if name == "all_creases" or len(nodes) == 0:
            continue
        try:
            uz_values = []
            for nid in nodes[:min(50, len(nodes))]:   # sample up to 50 nodes
                uz = mapdl.get(f"_UZ_{nid}", "NODE", int(nid), "U", "Z")
                uz_values.append(float(uz))
            if uz_values:
                mean_uz = float(np.mean(np.abs(uz_values)))
                angles[name] = math.degrees(math.atan2(mean_uz, 0.035))
        except Exception as exc:
            log.warning("Could not compute fold angle for crease '%s': %s", name, exc)
    return angles
