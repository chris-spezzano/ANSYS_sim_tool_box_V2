"""
HFSS Post-Processing — S-parameters, field visualization, EMI metrics.

Extracts
--------
- S-parameters (|S11|, |S21|, phase) vs frequency
- EMI shielding effectiveness SE = -20 log₁₀|S21| (dB)
- Absorption A = 1 - R - T (energy balance)
- Electric field distribution (E_x, E_y, E_z, |E|)
- Surface current density J_s (for conductor losses)

Energy partition
----------------
R = |S11|²       (reflectance — fraction of power reflected)
T = |S21|²       (transmittance — fraction of power transmitted)
A = 1 - R - T    (absorptance — fraction of power absorbed by material)

For a perfect metal (PEC): T = 0, A = 0, R = 1 (all reflected)
For an absorber: R ≈ 0, T ≈ 0, A ≈ 1 (all absorbed)
For a transparent window: T ≈ 1, R ≈ 0, A ≈ 0 (all transmitted)

Shielding effectiveness
-----------------------
SE_total (dB) = -20 log₁₀|S21|
SE_reflection = -10 log₁₀(1 - R)   = -10 log₁₀(T + A)
SE_absorption = SE_total - SE_reflection

For a thin metallic sheet:
    SE ≈ SE_R + SE_A + SE_M   (Schelkunoff theory)
where SE_R is reflection, SE_A is absorption, SE_M is multiple-reflection correction.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


def extract_s_parameters(
    hfss,
    port_names: list[str] | None = None,
    mode_index: int = 1,
    freq_points: int | None = None,
) -> dict[str, np.ndarray]:
    """Extract S-parameter data from a completed HFSS analysis.

    Parameters
    ----------
    hfss : HFSS object
    port_names : list[str] | None
        Port names to extract, e.g., ['FloquetPort1', 'FloquetPort2'].
        None = use ['FloquetPort1', 'FloquetPort2'].
    mode_index : int
        Which Floquet mode to report (1 = fundamental TE(0,0); see
        assign_floquet_ports()'s docstring for the mode-numbering
        convention). A multi-mode Floquet port REQUIRES this suffix --
        confirmed this session that available_report_quantities() lists
        entries as e.g. "S(FloquetPort1:1,FloquetPort1:1)", not the bare
        "S(FloquetPort1,FloquetPort1)" this function requested before,
        which made get_solution_data() return False silently ("Solution
        Data failed to load") instead of raising.
    freq_points : int | None
        Number of frequency points.  None = use all available.

    Returns
    -------
    dict with keys: 'freq_GHz', 'S11_mag', 'S21_mag', 'S11_phase', 'S21_phase'
    and derived: 'SE_dB', 'R', 'T', 'A'

    Example
    -------
    >>> results = extract_s_parameters(hfss)
    >>> import matplotlib.pyplot as plt
    >>> plt.plot(results['freq_GHz'], results['SE_dB'])
    >>> plt.xlabel('Frequency (GHz)');  plt.ylabel('SE (dB)')
    """
    try:
        post = hfss.post
        p1 = (port_names or ["FloquetPort1", "FloquetPort2"])[0]
        p2 = (port_names or ["FloquetPort1", "FloquetPort2"])[1]
        p1, p2 = f"{p1}:{mode_index}", f"{p2}:{mode_index}"

        # PostProcessorHFSS.get_report_data() does not exist in PyAEDT 1.1.0
        # (confirmed this session, AttributeError) -- get_solution_data() is
        # the real method, returning a SolutionData object whose values come
        # back through get_expression_data(expr, formula=...), not a
        # data_magnitude() method (also confirmed absent on SolutionData in
        # this version).
        s11_expr = f"S({p1},{p1})"
        s21_expr = f"S({p2},{p1})"
        solution = post.get_solution_data(
            expressions=[s11_expr, s21_expr],
            primary_sweep_variable="Freq",
        )
        # primary_sweep_values comes back already in the sweep's native unit
        # (GHz, since create_linear_count_sweep() in this project is always
        # called with unit="GHz") -- NOT Hz. Confirmed this session: dividing
        # by 1e9 here on top of that silently produced "0.000 GHz" labels
        # (e.g. 1.0 GHz became 1e-9) without raising, since this function
        # only ever had a single sweep point to mis-scale.
        freq_GHz = np.array([float(f) for f in solution.primary_sweep_values])

        _, s11_dB = solution.get_expression_data(s11_expr, formula="db20")
        _, s21_dB = solution.get_expression_data(s21_expr, formula="db20")
        s11_dB = np.asarray(s11_dB, dtype=float)
        s21_dB = np.asarray(s21_dB, dtype=float)
        s11_mag = 10 ** (s11_dB / 20)
        s21_mag = 10 ** (s21_dB / 20)

        # Energy partition
        R = s11_mag ** 2
        T = s21_mag ** 2
        A = np.clip(1.0 - R - T, 0, 1)

        # Shielding effectiveness
        SE_dB = -20 * np.log10(np.clip(s21_mag, 1e-10, 1.0))

        results = {
            "freq_GHz": freq_GHz,
            "S11_mag":  s11_mag,
            "S21_mag":  s21_mag,
            "S11_dB":   s11_dB,
            "S21_dB":   s21_dB,
            "R":        R,
            "T":        T,
            "A":        A,
            "SE_dB":    SE_dB,
        }

        log.info(
            "S-parameters extracted: %d freq points, SE range [%.1f, %.1f] dB",
            len(freq_GHz), SE_dB.min(), SE_dB.max(),
        )
        return results

    except Exception as exc:
        log.error("S-parameter extraction failed: %s", exc)
        raise


def export_field_file(
    hfss,
    quantity: str,
    setup_name: str,
    freq_GHz: float,
    output_path: str | Path,
    assignment: str = "AllObjects",
    objects_type: str = "Vol",
    extra_solutions: list[str] | None = None,
) -> Path | None:
    """Export a scalar/vector field quantity (e.g. 'Mag_E', 'Mag_H') to a
    native HFSS .fld file via Hfss.post.export_field_file() -- NOT HDF5 (an
    earlier version of this function, export_field_hdf5(), was named for a
    format it never actually produced, and called export_field_file() with
    kwarg names -- quantity/variation/filename/gridtype -- that don't match
    this PyAEDT version's real signature: quantity/solution/variations/
    output_file/assignment/objects_type/intrinsics. That mismatch meant the
    function had never actually worked).

    Modeled directly on a proven, previously-run implementation
    (D:/Projects/origami_emi_workflow/main/stages/stage3_hfss.py,
    _try_export_field_file()): tries "<setup> : LastAdaptive" first, then
    falls through extra_solutions (e.g. a named sweep), since which solution
    string is valid depends on whether freq_GHz matches the adaptive-pass
    frequency or a separate sweep point.

    Returns the output Path on success, None if every solution string failed
    (logged, not raised -- field export is a nice-to-have postprocessing
    step, not something that should fail the whole run).
    """
    output_path = Path(output_path)
    solutions_to_try = [f"{setup_name} : LastAdaptive"] + (extra_solutions or [])
    intrinsics = {"Freq": f"{freq_GHz}GHz", "Phase": "0deg"}

    for solution in solutions_to_try:
        try:
            ok = hfss.post.export_field_file(
                quantity=quantity,
                solution=solution,
                output_file=str(output_path),
                assignment=assignment,
                objects_type=objects_type,
                intrinsics=intrinsics,
            )
            if ok:
                log.info("%s exported -> %s (solution=%s)", quantity, output_path, solution)
                return output_path
        except Exception as exc:
            log.debug("%s export failed at %.3f GHz (solution=%s): %s", quantity, freq_GHz, solution, exc)
    log.warning("%s export failed at %.3f GHz (tried: %s)", quantity, freq_GHz, solutions_to_try)
    return None


def export_poynting_field(
    hfss,
    setup_name: str,
    freq_GHz: float,
    output_path: str | Path,
    assignment: str = "AllObjects",
    extra_solutions: list[str] | None = None,
) -> Path | None:
    """Export the Poynting-vector-magnitude field (power flow/deposition
    density) to a native .fld file.

    export_field_file()'s `quantity` argument only accepts AEDT's built-in
    named field quantities (Mag_E, Mag_H, etc.) -- Poynting isn't one of
    them, so it has to go through the raw Fields Calculator stack instead
    (hfss.post.ofieldsreporter, a dynamic gRPC object -- EnterQty/CalcOp/
    EnterVol/CalculatorWrite aren't discoverable via dir()/inspect, but are
    real, callable AEDT scripting methods). Same proven pattern as
    export_field_file() above, from the same reference implementation.
    """
    output_path = Path(output_path)
    solutions_to_try = [f"{setup_name} : LastAdaptive"] + (extra_solutions or [])
    intrinsics = {"Freq": f"{freq_GHz}GHz", "Phase": "0deg"}

    variation: list[str] = []
    try:
        nominal = hfss.available_variations.nominal_variation(dependent_params=False)
        for name, val in nominal.items():
            if hfss.variable_manager.variables[name].sweep:
                variation.extend([f"{name}:=", val])
    except Exception:
        pass
    for k, v in intrinsics.items():
        variation.extend([f"{k}:=", v])

    ofr = hfss.post.ofieldsreporter
    for solution in solutions_to_try:
        try:
            ofr.CalcStack("clear")
            ofr.EnterQty("Poynting")
            ofr.CalcOp("Mag")
            ofr.EnterVol(assignment)
            ofr.CalcOp("Value")
            ofr.CalculatorWrite(str(output_path), ["Solution:=", solution], variation)
            if output_path.exists():
                log.info("Poynting magnitude exported -> %s (solution=%s)", output_path, solution)
                return output_path
        except Exception as exc:
            log.debug("Poynting export failed at %.3f GHz (solution=%s): %s", freq_GHz, solution, exc)
    log.warning("Poynting export failed at %.3f GHz (tried: %s)", freq_GHz, solutions_to_try)
    return None


def save_sparameter_plots(
    results: dict[str, np.ndarray],
    output_dir: str | Path,
    dpi: int = 150,
) -> list[Path]:
    """Save SE, energy partition, and S-parameter plots.

    Parameters
    ----------
    results : dict
        Output from extract_s_parameters().
    output_dir : str | Path
        Directory for output PNGs.

    Returns
    -------
    list of Path objects for saved figures.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not available — S-parameter plots skipped")
        return []

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    freq = results["freq_GHz"]

    # SE plot
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(freq, results["SE_dB"], "b-", linewidth=1.5, label="SE total")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Shielding Effectiveness (dB)")
    ax.set_title("EMI Shielding Effectiveness")
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.tight_layout()
    p = out_dir / "SE_total_dB.png"
    fig.savefig(str(p), dpi=dpi)
    plt.close(fig)
    saved.append(p)

    # Energy partition
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.fill_between(freq, 0, results["R"],   alpha=0.6, label="Reflectance R")
    ax.fill_between(freq, results["R"], results["R"] + results["T"],
                    alpha=0.6, label="Transmittance T")
    ax.fill_between(freq, results["R"] + results["T"], 1.0,
                    alpha=0.6, label="Absorptance A")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Energy fraction")
    ax.set_title("Energy Partition (R + T + A = 1)")
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.tight_layout()
    p = out_dir / "energy_partition.png"
    fig.savefig(str(p), dpi=dpi)
    plt.close(fig)
    saved.append(p)

    # S11 and S21 dB
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(freq, results["S11_dB"], label="|S11| dB")
    ax.plot(freq, results["S21_dB"], label="|S21| dB")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Magnitude (dB)")
    ax.set_title("S-Parameters")
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.tight_layout()
    p = out_dir / "sparameters_dB.png"
    fig.savefig(str(p), dpi=dpi)
    plt.close(fig)
    saved.append(p)

    log.info("S-parameter plots saved to %s", out_dir)
    return saved


def write_s_parameters_csv(
    results: dict[str, np.ndarray],
    output_dir: str | Path,
    filename: str = "emi_results.csv",
) -> Path:
    """Write S-parameter results to CSV."""
    import csv
    out_dir  = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / filename

    keys = ["freq_GHz", "S11_dB", "S21_dB", "R", "T", "A", "SE_dB"]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(keys)
        for i in range(len(results["freq_GHz"])):
            writer.writerow([float(results[k][i]) for k in keys])

    log.info("EMI results CSV written → %s", csv_path)
    return csv_path
