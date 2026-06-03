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
    freq_points: int | None = None,
) -> dict[str, np.ndarray]:
    """Extract S-parameter data from a completed HFSS analysis.

    Parameters
    ----------
    hfss : HFSS object
    port_names : list[str] | None
        Port names to extract, e.g., ['FloquetPort:1', 'FloquetPort:2'].
        None = extract all ports.
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

        # Get frequency array
        freq_data = post.get_report_data(
            expression="Freq",
            primary_sweep="Freq",
        )
        freq_Hz = np.array([float(f) for f in freq_data.primary_sweep_values])
        freq_GHz = freq_Hz / 1e9

        # S11 magnitude
        s11_data = post.get_report_data(
            expression="dB(S(FloquetPort1,FloquetPort1))",
            primary_sweep="Freq",
        )
        s11_dB = np.array([float(v) for v in s11_data.data_magnitude()])
        s11_mag = 10 ** (s11_dB / 20)

        # S21 magnitude
        s21_data = post.get_report_data(
            expression="dB(S(FloquetPort2,FloquetPort1))",
            primary_sweep="Freq",
        )
        s21_dB = np.array([float(v) for v in s21_data.data_magnitude()])
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


def export_field_hdf5(
    hfss,
    output_dir: str | Path,
    field_type: str = "E",
    component:  str = "Mag_E",
    freq_GHz:   float | None = None,
    filename:   str = "field_data.h5",
) -> Path | None:
    """Export electric or magnetic field distribution to HDF5.

    Parameters
    ----------
    field_type : str
        'E' for electric field, 'H' for magnetic field.
    component : str
        Field component: 'Mag_E', 'ComplexMag_E', 'E_x', 'E_y', 'E_z', etc.
    freq_GHz : float | None
        Frequency to export.  None = last solved frequency.
    filename : str
        Output HDF5 filename.

    Returns
    -------
    Path to the HDF5 file, or None if export failed.
    """
    out_dir  = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h5_path  = out_dir / filename

    try:
        setup_name = hfss.setups[0]   # use first setup
        freq_str   = f"{freq_GHz}GHz" if freq_GHz else ""

        hfss.post.export_field_file(
            quantity   = component,
            variation  = {"Freq": freq_str} if freq_str else {},
            filename   = str(h5_path),
            gridtype   = "Cartesian",
        )
        log.info("Field data exported → %s", h5_path)
        return h5_path
    except Exception as exc:
        log.warning("Field export failed: %s", exc)
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
