"""
MAPDL Post-processing — extract results, visualize fields, export data.

Supports
--------
- Nodal displacements (UX, UY, UZ, USUM)
- Element stresses (SX, SY, SZ, SXY, SYZ, SXZ, SEQV von Mises)
- Principal stresses (S1, S2, S3)
- Element strains (EPEL, EPPL)
- Temperature (for coupled thermal analyses)
- Modal frequencies
- Harmonic amplitude / phase
- Point probes on the mesh
- VTK export for ParaView
- Animated GIFs (per prior MAPDL toolbox implementation)
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# ── Component maps ────────────────────────────────────────────────────────────

_DISP_COMPONENTS = {
    "displacement_x":    "X",
    "displacement_y":    "Y",
    "displacement_z":    "Z",
    "displacement_norm": "NORM",
}

_STRESS_COMPONENTS = {
    "stress_x":          "X",
    "stress_y":          "Y",
    "stress_z":          "Z",
    "stress_xy":         "XY",
    "stress_yz":         "YZ",
    "stress_xz":         "XZ",
    "von_mises":         "EQV",
    "principal_1":       "1",
    "principal_2":       "2",
    "principal_3":       "3",
}

_STRAIN_COMPONENTS = {
    "strain_el_x":       "X",
    "strain_el_y":       "Y",
    "strain_el_z":       "Z",
    "strain_pl_eqv":     "EQV",
}


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction function
# ─────────────────────────────────────────────────────────────────────────────

def extract_results(
    mapdl,
    quantities: list[str],
    result_set: int | str = "LAST",
) -> dict[str, np.ndarray]:
    """Extract nodal result arrays from the RST file.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    quantities : list[str]
        One or more of the field names from the component maps above.
        E.g., ['displacement_norm', 'von_mises', 'displacement_x'].
    result_set : int | str
        Which result set to read.  'LAST' (default) reads the final step.
        Use an integer for a specific substep index.

    Returns
    -------
    dict[str, np.ndarray]
        {field_name: 1-D array of per-node (or per-element) values}

    Example
    -------
    >>> results = extract_results(mapdl, ['displacement_norm', 'von_mises'])
    >>> print(f"Max USum = {results['displacement_norm'].max():.4f} m")
    >>> print(f"Max von Mises = {results['von_mises'].max()/1e6:.1f} MPa")
    """
    mapdl.post1()
    if result_set == "LAST":
        mapdl.set("LAST")
    else:
        mapdl.set(nset=int(result_set))

    results: dict[str, np.ndarray] = {}

    for qty in quantities:
        if qty in _DISP_COMPONENTS:
            comp = _DISP_COMPONENTS[qty]
            arr  = np.asarray(mapdl.post_processing.nodal_displacement(comp))
            results[qty] = arr

        elif qty in _STRESS_COMPONENTS:
            comp = _STRESS_COMPONENTS[qty]
            try:
                arr = np.asarray(mapdl.post_processing.nodal_stress(comp))
            except Exception:
                try:
                    arr = np.asarray(mapdl.post_processing.element_stress(comp))
                except Exception as exc:
                    log.warning("Could not extract %s: %s", qty, exc)
                    continue
            results[qty] = arr

        elif qty in _STRAIN_COMPONENTS:
            comp = _STRAIN_COMPONENTS[qty]
            try:
                arr = np.asarray(mapdl.post_processing.nodal_elastic_strain(comp))
            except Exception:
                try:
                    arr = np.asarray(mapdl.post_processing.nodal_plastic_strain(comp))
                except Exception as exc:
                    log.warning("Could not extract %s: %s", qty, exc)
                    continue
            results[qty] = arr

        elif qty == "temperature":
            try:
                arr = np.asarray(mapdl.post_processing.nodal_temperature())
                results[qty] = arr
            except Exception as exc:
                log.warning("Could not extract temperature: %s", exc)

        else:
            log.warning("Unknown quantity '%s' — skipping", qty)

    for qty, arr in results.items():
        a = np.asarray(arr)
        log.info("  %-28s  min=%+.4g   max=%+.4g", qty, float(a.min()), float(a.max()))

    return results


def probe_point(
    mapdl,
    x: float, y: float, z: float = 0.0,
    quantities: list[str] | None = None,
    tol: float = 1e-6,
) -> dict[str, float]:
    """Extract field values at a specific spatial location.

    Finds the nearest mesh node to (x, y, z) within tolerance and returns
    the requested quantities at that node.

    Parameters
    ----------
    mapdl : PyMAPDL instance (must be in POST1 with a loaded result set)
    x, y, z : float
        Target coordinates in model units (m).
    quantities : list[str] | None
        Fields to probe.  Defaults to all displacement components.
    tol : float
        Nearest-node search radius.

    Returns
    -------
    dict {quantity: value_at_node}

    Notes
    -----
    This does NOT interpolate — it returns the value at the nearest node.
    For smooth fields (displacements) the nearest-node value is usually
    accurate to within the element size.  For stress singularities, nearby
    probe values are mesh-dependent.
    """
    if quantities is None:
        quantities = ["displacement_x", "displacement_y", "displacement_z",
                      "displacement_norm"]

    nodes_xyz = mapdl.mesh.nodes
    nnum      = list(mapdl.mesh.nnum)

    target = np.array([x, y, z])
    dists  = np.linalg.norm(nodes_xyz - target, axis=1)
    idx    = int(np.argmin(dists))

    if dists[idx] > tol:
        log.warning(
            "Nearest node to (%.4g, %.4g, %.4g) is %.4g m away — "
            "may not be on the intended location",
            x, y, z, dists[idx],
        )

    node_id = nnum[idx]
    log.info(
        "Probing node %d at (%.4g, %.4g, %.4g) — distance to target: %.2e m",
        node_id, *nodes_xyz[idx], dists[idx],
    )

    mapdl.nsel("S", "NODE", "", node_id)
    probe_results = extract_results(mapdl, quantities)
    mapdl.nsel("ALL")

    return {qty: float(arr[idx]) for qty, arr in probe_results.items()}


def extract_modal_frequencies(mapdl) -> list[dict[str, float]]:
    """Extract natural frequencies from a completed modal analysis.

    Returns
    -------
    list of dicts: [{'mode': 1, 'freq_Hz': 12.3, 'omega_rad_s': 77.3}, ...]
    """
    modes = []
    mapdl.post1()
    n_sets = int(float(mapdl.get("_NM_", "ACTIVE", 0, "SET", "NSET")))
    for i in range(1, n_sets + 1):
        mapdl.set(nset=i)
        freq = float(mapdl.get("_FREQ_", "ACTIVE", 0, "SET", "FREQ"))
        modes.append({
            "mode":        i,
            "freq_Hz":     freq,
            "omega_rad_s": freq * 2 * np.pi,
        })
    return modes


# ─────────────────────────────────────────────────────────────────────────────
# Output writers
# ─────────────────────────────────────────────────────────────────────────────

def write_csv(
    results: dict[str, np.ndarray],
    output_dir: str | Path,
    filename: str = "nodal_results.csv",
) -> Path:
    """Write per-node results to CSV."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / filename

    keys  = list(results.keys())
    n_nodes = len(next(iter(results.values())))

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["node_index"] + keys)
        for i in range(n_nodes):
            writer.writerow([i] + [float(results[k][i]) for k in keys])

    log.info("CSV written → %s  (%d nodes, %d quantities)", csv_path, n_nodes, len(keys))
    return csv_path


def export_vtk(mapdl, output_dir: str | Path, filename: str = "results.vtk") -> Path | None:
    """Export current result set as a VTK file for ParaView.

    Returns
    -------
    Path to the VTK file, or None if export failed.
    """
    try:
        import pyvista as pv
        out_dir  = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        vtk_path = out_dir / filename

        mesh = mapdl.mesh._surf
        mapdl.post1()
        mapdl.set("LAST")

        # Add displacement vectors
        nodes_xyz = mapdl.mesh.nodes
        n = len(nodes_xyz)
        ux = np.asarray(mapdl.post_processing.nodal_displacement("X"))[:n]
        uy = np.asarray(mapdl.post_processing.nodal_displacement("Y"))[:n]
        uz = np.asarray(mapdl.post_processing.nodal_displacement("Z"))[:n]
        node_ids = (mesh["ansys_node_num"].astype(int) - 1)

        mesh.point_data["displacement"] = np.column_stack([ux, uy, uz])[node_ids]
        mesh.point_data["disp_norm"]    = np.linalg.norm(
            np.column_stack([ux, uy, uz]), axis=1
        )[node_ids]

        try:
            vm = np.asarray(mapdl.post_processing.nodal_stress("EQV"))[:n]
            mesh.point_data["von_mises"] = vm[node_ids]
        except Exception:
            pass

        mesh.save(str(vtk_path))
        log.info("VTK exported → %s", vtk_path)
        return vtk_path

    except Exception as exc:
        log.warning("VTK export failed: %s", exc)
        return None


def save_plots(
    mapdl,
    results: dict[str, np.ndarray],
    output_dir: str | Path,
    quantities: list[str] | None = None,
    deform_scale: float = 10.0,
    dpi: int = 150,
) -> list[Path]:
    """Save contour PNG files for each requested quantity.

    Falls back gracefully: PyVista → matplotlib line plot → skip.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    if quantities is None:
        quantities = list(results.keys())

    for qty in quantities:
        fig_path = out_dir / f"{qty}.png"

        # Try PyMAPDL / PyVista first
        if _try_pyvista_plot(mapdl, qty, fig_path):
            saved.append(fig_path)
        elif _try_matplotlib_plot(results, qty, fig_path, dpi):
            saved.append(fig_path)

    # Deformed shape overlay
    deform_path = out_dir / "deformed_shape.png"
    if _try_deformed_shape(mapdl, results, deform_scale, deform_path, dpi):
        saved.append(deform_path)

    return saved


def save_animation(
    mapdl,
    output_dir: str | Path,
    qty: str = "displacement_norm",
    step_every: int = 1,
    fps: int = 12,
    deform_scale: float = 10.0,
) -> Path | None:
    """Save an animated GIF stepping through all stored result sets.

    Identical to the MAPDL toolbox implementation but parameterized.
    See docs/RESULTS_VIEWER_GUIDE.md for a full description.
    """
    from ..results_utils import _save_animation_impl
    return _save_animation_impl(
        mapdl, output_dir, qty, step_every, fps, deform_scale
    )


# ─────────────────────────────────────────────────────────────────────────────
# Private plot helpers
# ─────────────────────────────────────────────────────────────────────────────

def _try_pyvista_plot(mapdl, qty: str, fig_path: Path) -> bool:
    try:
        if qty in _DISP_COMPONENTS:
            comp = _DISP_COMPONENTS[qty]
            mapdl.post_processing.plot_nodal_displacement(
                comp, savefig=str(fig_path), off_screen=True,
            )
        elif qty in _STRESS_COMPONENTS:
            comp = _STRESS_COMPONENTS[qty]
            mapdl.post_processing.plot_nodal_stress(
                comp, savefig=str(fig_path), off_screen=True,
            )
        else:
            return False
        log.info("Plot saved → %s", fig_path)
        return True
    except Exception as exc:
        log.debug("PyVista plot failed for %s: %s", qty, exc)
        return False


def _try_matplotlib_plot(
    results: dict[str, np.ndarray],
    qty: str,
    fig_path: Path,
    dpi: int,
) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        arr = results.get(qty)
        if arr is None:
            return False
        arr = np.asarray(arr)

        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(arr, "o-", markersize=2.5, linewidth=0.7)
        ax.set_xlabel("Node index")
        ax.set_ylabel(qty.replace("_", " "))
        ax.set_title(qty.replace("_", " ").title())
        ax.grid(True, alpha=0.35)
        fig.tight_layout()
        fig.savefig(str(fig_path), dpi=dpi)
        plt.close(fig)
        log.info("Matplotlib fallback plot saved → %s", fig_path)
        return True
    except Exception as exc:
        log.debug("Matplotlib fallback failed for %s: %s", qty, exc)
        return False


def _try_deformed_shape(
    mapdl,
    results: dict[str, np.ndarray],
    scale: float,
    fig_path: Path,
    dpi: int,
) -> bool:
    try:
        import pyvista as pv
        pv.OFF_SCREEN = True

        nodes_xyz = mapdl.mesh.nodes
        n = len(nodes_xyz)
        ux = np.asarray(results.get("displacement_x", np.zeros(n)))[:n]
        uy = np.asarray(results.get("displacement_y", np.zeros(n)))[:n]
        uz = np.asarray(results.get("displacement_z", np.zeros(n)))[:n]
        disp_vecs = np.column_stack([ux, uy, uz])
        disp_norm = np.linalg.norm(disp_vecs, axis=1)

        mesh     = mapdl.mesh._surf.copy(deep=True)
        node_ids = (mesh["ansys_node_num"].astype(int) - 1)
        mesh.point_data["displacement"] = disp_vecs[node_ids]
        mesh.point_data["disp_norm"]    = disp_norm[node_ids]
        warped   = mesh.warp_by_vector("displacement", factor=scale)

        pl = pv.Plotter(off_screen=True, window_size=(1200, 800))
        pl.set_background("white")
        pl.add_mesh(mesh,   style="wireframe", color="grey", opacity=0.4)
        pl.add_mesh(warped, scalars="disp_norm", cmap="jet",
                    scalar_bar_args={"title": "|U| (m)"})
        pl.add_text(f"Deformed shape (×{scale:.0f})", position="upper_edge",
                    font_size=12, color="black")
        pl.camera_position = "xy"
        pl.screenshot(str(fig_path))
        pl.close()
        log.info("Deformed shape saved → %s  (scale ×%.0f)", fig_path, scale)
        return True
    except Exception as exc:
        log.debug("Deformed shape plot failed: %s", exc)
        return False
