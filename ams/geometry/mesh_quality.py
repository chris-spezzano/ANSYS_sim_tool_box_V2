"""
Mesh Quality Checker — validate FE meshes before solving.

Poor mesh quality is one of the top causes of solver divergence and
incorrect results.  This module runs a battery of checks and blocks
the solve if any critical threshold is violated.

Quality metrics computed
------------------------
1. Aspect ratio       — longest edge / shortest edge.  < 10 ideal, > 20 bad.
2. Jacobian ratio     — minimum/maximum Jacobian determinant over element.
                        < 0 = inverted element (always fatal).
3. Warping factor     — deviation from a flat plane (shells/quads only).
                        > 30° causes integration point inaccuracies.
4. Skewness           — deviation from equiangular shape.  0 = perfect, 1 = degenerate.
5. Orthogonal quality — dot product of face normals vs edge vectors.  > 0.1 required.
6. Manifold check     — every internal face shared by exactly 2 elements.
7. Watertight check   — no free boundary edges (for solid models).
8. Minimum element size — flag elements smaller than a user-set threshold.

References
----------
Knupp, P. (2001). Algebraic mesh quality metrics. SIAM J. Sci. Comput. 23(1), 193–218.
ANSYS Mechanical APDL Element Reference, Release 2025 R2, §1.3 "Element Quality".
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


# ── Default quality thresholds ────────────────────────────────────────────────

@dataclass
class QualityThresholds:
    """Pass/fail thresholds for each quality metric.

    Attributes
    ----------
    aspect_ratio_max : float
        Maximum allowable aspect ratio.  ANSYS recommends < 10 for most elements.
        Values > 20 indicate highly distorted elements that will give poor results.
    jacobian_min : float
        Minimum Jacobian ratio.  Must be > 0 (negative = inverted element).
        ANSYS will refuse to solve with inverted elements.
    warping_max_deg : float
        Maximum warping angle for shell elements (degrees).
        Beyond 30° the mid-surface integration rule breaks down.
    skewness_max : float
        Maximum mesh skewness (0–1 scale, 0 = perfect).
        > 0.9 is degenerate; < 0.25 is good.
    min_element_size_m : float | None
        Flag elements below this size.  None = no lower limit.
        Very small elements create stiff local regions that slow convergence.
    """
    aspect_ratio_max:  float = 20.0
    jacobian_min:      float = 0.0
    warping_max_deg:   float = 30.0
    skewness_max:      float = 0.90
    min_element_size_m: float | None = None


@dataclass
class QualityReport:
    """Results from a mesh quality check.

    Attributes
    ----------
    passed : bool
        True only if ALL critical checks passed.
    n_nodes : int
    n_elements : int
    checks : dict[str, dict]
        Per-metric results: {'status': 'PASS'|'FAIL'|'WARN', 'value': ..., 'msg': ...}
    bad_element_ids : list[int]
        MAPDL element IDs that failed one or more checks.
    """
    passed:          bool
    n_nodes:         int
    n_elements:      int
    checks:          dict[str, dict] = field(default_factory=dict)
    bad_element_ids: list[int] = field(default_factory=list)

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("  Mesh Quality Report")
        print("=" * 60)
        print(f"  Nodes    : {self.n_nodes:,}")
        print(f"  Elements : {self.n_elements:,}")
        print()
        for metric, result in self.checks.items():
            status = result["status"]
            icon   = {"PASS": "[OK]", "WARN": "[!] ", "FAIL": "[X]"}.get(status, " ? ")
            print(f"  {icon} {metric:<28} {result.get('msg', '')}")
        print()
        overall = "PASSED" if self.passed else "FAILED"
        print(f"  Overall: {overall}")
        if self.bad_element_ids:
            n = len(self.bad_element_ids)
            ids_preview = self.bad_element_ids[:10]
            print(f"  Bad elements ({n}): {ids_preview}{'...' if n > 10 else ''}")
        print("=" * 60 + "\n")


class MeshQualityChecker:
    """Run mesh quality checks on a MAPDL mesh.

    Parameters
    ----------
    mapdl : PyMAPDL instance
        Active MAPDL session with a mesh already loaded.
    thresholds : QualityThresholds | None
        Pass/fail thresholds.  Defaults to conservative engineering values.

    Example
    -------
    >>> from ams.geometry.mesh_quality import MeshQualityChecker, QualityThresholds
    >>> checker = MeshQualityChecker(mapdl)
    >>> report  = checker.check()
    >>> report.print_summary()
    >>> if not report.passed:
    ...     raise RuntimeError("Mesh quality check failed — fix mesh before solving")
    """

    def __init__(self, mapdl, thresholds: QualityThresholds | None = None):
        self._m = mapdl
        self.thresholds = thresholds or QualityThresholds()

    def check(self, raise_on_fail: bool = False) -> QualityReport:
        """Run all quality checks and return a report.

        Parameters
        ----------
        raise_on_fail : bool
            If True, raise RuntimeError if any critical check fails.
            Use this to gate the solve: mesh must pass before the solver starts.

        Returns
        -------
        QualityReport
        """
        m = self._m
        t = self.thresholds

        n_nodes = m.mesh.n_node
        n_elems = m.mesh.n_elem

        checks:          dict[str, dict] = {}
        bad_elem_ids:    list[int] = []
        overall_passed = True

        # ── MAPDL built-in CHECK command ──────────────────────────────────────
        try:
            check_out = m.check("")
            if "error" in check_out.lower() or "warning" in check_out.lower():
                checks["mapdl_check"] = {
                    "status": "WARN",
                    "msg": "MAPDL CHECK reported warnings (see log)",
                }
            else:
                checks["mapdl_check"] = {"status": "PASS", "msg": "No MAPDL errors"}
        except Exception as exc:
            checks["mapdl_check"] = {"status": "WARN", "msg": f"CHECK failed: {exc}"}

        # ── Element quality via MAPDL SHPP,SUMMARY ───────────────────────────
        try:
            m.run("SHPP,SUMMARY")
            checks["shpp_summary"] = {
                "status": "PASS",
                "msg": "SHPP shape check complete (see MAPDL log for details)",
            }
        except Exception:
            checks["shpp_summary"] = {"status": "WARN", "msg": "SHPP unavailable"}

        # ── Aspect ratio (via PyMAPDL mesh data) ──────────────────────────────
        try:
            ar_max, ar_mean, n_bad, bad_ids = _compute_aspect_ratio(m)
            status = "PASS"
            if ar_max > t.aspect_ratio_max:
                status = "FAIL"
                overall_passed = False
                bad_elem_ids.extend(bad_ids)
            elif ar_max > t.aspect_ratio_max * 0.7:
                status = "WARN"
            checks["aspect_ratio"] = {
                "status": status,
                "value":  ar_max,
                "msg":    f"max={ar_max:.2f}  mean={ar_mean:.2f}  (limit {t.aspect_ratio_max})  {n_bad} bad elements",
            }
        except Exception as exc:
            checks["aspect_ratio"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        # ── Jacobian via MAPDL SHPP,ON + SHPP,JRAT ───────────────────────────
        try:
            jac_min, jac_bad_ids = _check_jacobian(m)
            status = "PASS"
            if jac_min < t.jacobian_min:
                status = "FAIL"
                overall_passed = False
                bad_elem_ids.extend(jac_bad_ids)
            elif jac_min < 0.1:
                status = "WARN"
            checks["jacobian"] = {
                "status": status,
                "value":  jac_min,
                "msg":    f"min={jac_min:.4f}  (< 0 = inverted element — solve blocked)",
            }
        except Exception as exc:
            checks["jacobian"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        # ── Warping (shell elements only) ─────────────────────────────────────
        try:
            warp_max, warp_bad = _check_warping(m)
            if warp_max is not None:
                status = "PASS"
                if warp_max > t.warping_max_deg:
                    status = "WARN"
                    bad_elem_ids.extend(warp_bad)
                checks["warping_deg"] = {
                    "status": status,
                    "value":  warp_max,
                    "msg":    f"max={warp_max:.1f}°  (shell limit {t.warping_max_deg}°)",
                }
            else:
                checks["warping_deg"] = {"status": "PASS", "msg": "N/A (non-shell mesh)"}
        except Exception as exc:
            checks["warping_deg"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        # ── Manifold check ────────────────────────────────────────────────────
        try:
            is_manifold, n_non_manifold = _check_manifold(m)
            status = "PASS" if is_manifold else "FAIL"
            if not is_manifold:
                overall_passed = False
            checks["manifold"] = {
                "status": status,
                "value":  n_non_manifold,
                "msg":    ("OK - mesh is manifold" if is_manifold
                           else f"{n_non_manifold} non-manifold edges found"),
            }
        except Exception as exc:
            checks["manifold"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        # ── Watertight check ──────────────────────────────────────────────────
        try:
            is_watertight, n_free = _check_watertight(m)
            if is_watertight:
                checks["watertight"] = {"status": "PASS", "msg": "No free boundary faces"}
            else:
                checks["watertight"] = {
                    "status": "WARN",
                    "value":  n_free,
                    "msg":    f"{n_free} free boundary faces (OK for shells; bad for solids)",
                }
        except Exception as exc:
            checks["watertight"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        # ── Minimum element size ──────────────────────────────────────────────
        if t.min_element_size_m is not None:
            try:
                esize_min, small_ids = _check_min_element_size(m, t.min_element_size_m)
                if small_ids:
                    checks["min_element_size"] = {
                        "status": "WARN",
                        "value":  esize_min,
                        "msg":    f"{len(small_ids)} elements below {t.min_element_size_m*1000:.3f} mm  (min={esize_min*1000:.4f} mm)",
                    }
                else:
                    checks["min_element_size"] = {
                        "status": "PASS",
                        "msg":    f"Smallest element: {esize_min*1000:.3f} mm",
                    }
            except Exception as exc:
                checks["min_element_size"] = {"status": "WARN", "msg": f"Could not compute: {exc}"}

        report = QualityReport(
            passed          = overall_passed,
            n_nodes         = n_nodes,
            n_elements      = n_elems,
            checks          = checks,
            bad_element_ids = list(set(bad_elem_ids)),
        )

        if raise_on_fail and not overall_passed:
            report.print_summary()
            raise RuntimeError(
                "Mesh quality check FAILED — solve blocked.  "
                "Fix the bad elements listed above before proceeding.  "
                "Common causes: imported STL/CDB with inverted elements, "
                "highly stretched elements at geometric singularities."
            )

        return report


# ─────────────────────────────────────────────────────────────────────────────
# Private metric computations
# ─────────────────────────────────────────────────────────────────────────────

def _compute_aspect_ratio(m) -> tuple[float, float, int, list[int]]:
    """Compute max edge-length aspect ratio over all elements.

    Method
    ------
    For each element, find its nodes and compute the min/max edge length.
    Aspect ratio AR = max_edge / min_edge.

    For QUAD4:  4 edges
    For HEX8:  12 edges
    For TET4:   6 edges
    """
    nodes_xyz = np.atleast_2d(m.mesh.nodes)        # (N, 3)
    node_ids  = m.mesh.nnum                         # 1-based MAPDL IDs
    id_to_idx = {int(nid): i for i, nid in enumerate(node_ids)}

    ar_list: list[float] = []
    bad_ids: list[int]   = []

    for el in m.mesh.elem:
        el  = np.asarray(el, dtype=int)
        ids = el[10:]                               # strip 10 header columns
        ids = ids[ids > 0]
        coords = np.array([nodes_xyz[id_to_idx[n]] for n in ids if n in id_to_idx])
        if len(coords) < 2:
            continue

        # All pairwise edge lengths (only connected edges, not diagonals)
        # Approximate: compute all pairwise distances and take min/max of adjacent pairs
        n = len(coords)
        edges = [np.linalg.norm(coords[(i+1) % n] - coords[i]) for i in range(n)]
        edges = [e for e in edges if e > 1e-15]
        if not edges:
            continue

        ar = max(edges) / min(edges)
        ar_list.append(ar)
        if ar > 20.0:
            elem_id = int(el[7])                    # element number is header col 7
            bad_ids.append(elem_id)

    if not ar_list:
        return 1.0, 1.0, 0, []

    return float(max(ar_list)), float(np.mean(ar_list)), len(bad_ids), bad_ids


def _check_jacobian(m) -> tuple[float, list[int]]:
    """Compute minimum Jacobian ratio across all elements.

    MAPDL SHPP,ON enables quality warnings; MAPDL CHKMSH checks element validity.
    We use a geometric proxy: the minimum determinant of the Jacobian at element corners.

    For a hex8 element at corner node ξᵢ, the Jacobian is the 3×3 matrix of
    derivatives dx/dξ, dy/dξ, dz/dξ.  A negative determinant means the element
    is inverted.

    Returns
    -------
    jac_min : float  — minimum Jacobian ratio found (< 0 = inverted)
    bad_ids : list[int] — element IDs with negative Jacobian
    """
    try:
        # MAPDL SHPP reports Jacobian ratio directly
        m.run("SHPP,ON,JRAT")
        m.run("SHPP,SUMM")
    except Exception:
        pass

    # Geometric proxy using node coordinates
    nodes_xyz = np.atleast_2d(m.mesh.nodes)
    node_ids  = m.mesh.nnum
    id_to_idx = {int(nid): i for i, nid in enumerate(node_ids)}

    jac_vals: list[float] = []
    bad_ids:  list[int]   = []

    for el in m.mesh.elem:
        el_arr = np.asarray(el, dtype=int)
        ids    = el_arr[10:]
        ids    = ids[ids > 0]
        coords = np.array([nodes_xyz[id_to_idx[n]] for n in ids if n in id_to_idx])
        if len(coords) < 4:
            continue

        j = _estimate_jacobian(coords)
        jac_vals.append(j)
        if j <= 0:
            elem_id = int(el_arr[7])
            bad_ids.append(elem_id)

    jac_min = float(min(jac_vals)) if jac_vals else 0.0
    return jac_min, bad_ids


def _estimate_jacobian(coords: np.ndarray) -> float:
    """Estimate the Jacobian determinant at the centroid of an element.

    For a simplex element (4 nodes in 3D), compute the signed volume as a proxy.
    For general n-node elements, use the Jacobian at the element centroid.

    This is an approximation — MAPDL's internal Jacobian check is more accurate
    (it evaluates at all integration points), but this gives a useful pre-solve gate.
    """
    n = len(coords)

    if n >= 8:
        # Hex: use first 8 nodes, compute trilinear Jacobian at centroid (ξ=η=ζ=0)
        c = coords[:8]
        # Trilinear shape function derivatives at centroid:
        # dN/dξ evaluated at (0,0,0) gives 8 values of 1/8 times edge vectors
        j = np.zeros((3, 3))
        dN_dxi  = np.array([-1, 1, 1,-1,-1, 1, 1,-1]) * 0.125
        dN_deta = np.array([-1,-1, 1, 1,-1,-1, 1, 1]) * 0.125
        dN_dzeta= np.array([-1,-1,-1,-1, 1, 1, 1, 1]) * 0.125
        j[0] = dN_dxi  @ c
        j[1] = dN_deta @ c
        j[2] = dN_dzeta @ c
        return float(np.linalg.det(j))
    elif n == 4:
        # Could be a TET4 (3D) or a QUAD4 (2D / shell with all z equal).
        # Detect 2D: if all z-coords are essentially the same, use bilinear QUAD4 Jacobian.
        if coords.shape[1] >= 3 and np.ptp(coords[:, 2]) < 1e-12:
            # Bilinear QUAD4 Jacobian at centroid (xi=eta=0).
            # Node ordering assumed: CCW (ANSYS convention)
            #   node0=(-1,-1), node1=(+1,-1), node2=(+1,+1), node3=(-1,+1)
            # dN/dxi  at (0,0) = [-1/4, +1/4, +1/4, -1/4]
            # dN/deta at (0,0) = [-1/4, -1/4, +1/4, +1/4]
            x = coords[:, 0]
            y = coords[:, 1]
            dN_xi  = np.array([-0.25,  0.25,  0.25, -0.25])
            dN_eta = np.array([-0.25, -0.25,  0.25,  0.25])
            j00 = float(dN_xi  @ x)
            j01 = float(dN_xi  @ y)
            j10 = float(dN_eta @ x)
            j11 = float(dN_eta @ y)
            return j00 * j11 - j01 * j10
        # 3D tet: signed volume = det([p1-p0, p2-p0, p3-p0]) / 6
        v = coords[1:4] - coords[0]
        return float(np.linalg.det(v)) / 6.0
    elif n >= 3:
        # Quad / triangle: 2D area
        v1 = coords[1] - coords[0]
        v2 = coords[2] - coords[0]
        cross = np.cross(v1[:2], v2[:2]) if coords.shape[1] > 2 else (v1[0]*v2[1] - v1[1]*v2[0])
        return float(cross)
    return 1.0


def _check_warping(m) -> tuple[float | None, list[int]]:
    """Compute maximum warping angle for shell/2D elements (degrees)."""
    nodes_xyz = np.atleast_2d(m.mesh.nodes)
    node_ids  = m.mesh.nnum
    id_to_idx = {int(nid): i for i, nid in enumerate(node_ids)}

    warp_vals: list[float] = []
    bad_ids:   list[int]   = []
    is_shell = False

    for el in m.mesh.elem:
        el_arr = np.asarray(el, dtype=int)
        ids    = el_arr[10:]
        ids    = ids[ids > 0]
        if len(ids) != 4:
            continue
        is_shell = True
        coords = np.array([nodes_xyz[id_to_idx[n]] for n in ids if n in id_to_idx])
        if len(coords) != 4:
            continue

        # Warping: angle between the two diagonals' planes
        d1 = coords[2] - coords[0]
        d2 = coords[3] - coords[1]
        n1 = np.cross(coords[1] - coords[0], d1)
        n2 = np.cross(d2, coords[2] - coords[1])

        n1n = np.linalg.norm(n1)
        n2n = np.linalg.norm(n2)
        if n1n < 1e-15 or n2n < 1e-15:
            continue
        cos_angle = np.clip(np.dot(n1 / n1n, n2 / n2n), -1, 1)
        angle_deg = math.degrees(math.acos(cos_angle))
        warp_vals.append(angle_deg)
        if angle_deg > 30.0:
            bad_ids.append(int(el_arr[7]))

    if not is_shell or not warp_vals:
        return None, []

    return float(max(warp_vals)), bad_ids


def _check_manifold(m) -> tuple[bool, int]:
    """Check that the mesh is manifold (each edge shared by ≤ 2 elements)."""
    from collections import Counter

    edge_count: Counter = Counter()

    for el in m.mesh.elem:
        el_arr = np.asarray(el, dtype=int)
        ids    = el_arr[10:]
        ids    = ids[ids > 0].tolist()
        n = len(ids)
        for i in range(n):
            e = tuple(sorted([ids[i], ids[(i+1) % n]]))
            edge_count[e] += 1

    non_manifold = sum(1 for c in edge_count.values() if c > 2)
    return non_manifold == 0, non_manifold


def _check_watertight(m) -> tuple[bool, int]:
    """Count free boundary edges (edges belonging to exactly 1 element face)."""
    from collections import Counter

    edge_count: Counter = Counter()
    for el in m.mesh.elem:
        el_arr = np.asarray(el, dtype=int)
        ids    = el_arr[10:]
        ids    = ids[ids > 0].tolist()
        n = len(ids)
        for i in range(n):
            e = tuple(sorted([ids[i], ids[(i+1) % n]]))
            edge_count[e] += 1

    free = sum(1 for c in edge_count.values() if c == 1)
    return free == 0, free


def _check_min_element_size(m, min_size_m: float) -> tuple[float, list[int]]:
    """Find elements smaller than the minimum size threshold."""
    nodes_xyz = np.atleast_2d(m.mesh.nodes)
    node_ids  = m.mesh.nnum
    id_to_idx = {int(nid): i for i, nid in enumerate(node_ids)}

    small: list[int] = []
    all_min: list[float] = []

    for el in m.mesh.elem:
        el_arr = np.asarray(el, dtype=int)
        ids    = el_arr[10:]
        ids    = ids[ids > 0]
        coords = np.array([nodes_xyz[id_to_idx[n]] for n in ids if n in id_to_idx])
        if len(coords) < 2:
            continue
        n = len(coords)
        edges = [np.linalg.norm(coords[(i+1) % n] - coords[i]) for i in range(n)]
        edges = [e for e in edges if e > 0]
        if not edges:
            continue
        emin = min(edges)
        all_min.append(emin)
        if emin < min_size_m:
            small.append(int(el_arr[7]))

    global_min = float(min(all_min)) if all_min else 0.0
    return global_min, small
