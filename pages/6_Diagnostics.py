"""Page 6 — Diagnostics: live simulation health dashboard."""

import streamlit as st
import yaml, time
from pathlib import Path

st.set_page_config(page_title="Diagnostics", layout="wide")
st.title("Step 6 · Live Diagnostics")
st.markdown("""
Monitor your simulation in real time.  This page polls the live MAPDL/HFSS
session and reports convergence, port status, RAM usage, and RST file size.

**Start the diagnostic dashboard BEFORE launching `mapdl.solve()`.**
The background thread polls every few seconds while the solve runs in foreground.
""")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh: return yaml.safe_load(fh)
    return {}

cfg = _load_cfg()

# ── Port status ────────────────────────────────────────────────────────────────
st.subheader("Port Status")
if st.button("Refresh Port Status"):
    try:
        from ams.resources.manager import check_ports
        status = check_ports()
        c1, c2, c3, c4 = st.columns(4)
        for i, (port, occupied) in enumerate(status.items()):
            col = [c1, c2, c3, c4][i % 4]
            icon = "🔴" if occupied else "🟢"
            col.metric(f"{icon} Port {port}", "OCCUPIED" if occupied else "free")
    except Exception as e:
        st.error(f"Error: {e}")

# ── Process health ─────────────────────────────────────────────────────────────
st.subheader("ANSYS Process Health")
if st.button("Scan Processes"):
    try:
        import psutil
        ansys_names = {"ansys252","ansys251","ansys242","ansysedt","mapdl"}
        found = []
        for proc in psutil.process_iter(["pid","name","memory_info","cpu_percent","status"]):
            try:
                name = (proc.info["name"] or "").lower().replace(".exe","")
                if name in ansys_names:
                    mi = proc.info["memory_info"]
                    found.append({
                        "PID": proc.info["pid"],
                        "Name": proc.info["name"],
                        "RAM (MB)": f"{mi.rss/1024**2:.0f}" if mi else "?",
                        "CPU %": f"{proc.info['cpu_percent']:.1f}",
                        "Status": proc.info["status"],
                    })
            except Exception:
                pass
        if found:
            import pandas as pd
            st.dataframe(pd.DataFrame(found))
        else:
            st.info("No ANSYS processes found.")
    except ImportError:
        st.warning("Install psutil for process monitoring: pip install psutil")
    except Exception as e:
        st.error(f"Error: {e}")

# ── Diagnostics log viewer ─────────────────────────────────────────────────────
st.subheader("Diagnostics Log")
diag_csv = Path(cfg.get("output", {}).get("dir", "outputs")) / "diagnostics.csv"
if diag_csv.exists():
    try:
        import pandas as pd
        import matplotlib.pyplot as plt

        df = pd.read_csv(diag_csv)
        st.markdown(f"Loaded `{diag_csv}` — {len(df)} snapshots")

        tab1, tab2, tab3 = st.tabs(["Table", "Residuals", "Resource Usage"])

        with tab1:
            st.dataframe(df.tail(50))

        with tab2:
            if "f_residual" in df.columns and df["f_residual"].notna().any():
                fig, ax = plt.subplots(figsize=(8, 3))
                ax.semilogy(df["elapsed_s"], df["f_residual"].abs(), label="Force residual")
                if "u_residual" in df.columns:
                    ax.semilogy(df["elapsed_s"], df["u_residual"].abs(), label="Disp residual")
                ax.axhline(0.005, color="red", linestyle="--", label="ε_F = 0.5% threshold")
                ax.set_xlabel("Elapsed time (s)"); ax.set_ylabel("Residual norm")
                ax.legend(); ax.grid(True, alpha=0.3)
                st.pyplot(fig)
            else:
                st.info("No residual data recorded.")

        with tab3:
            if "ram_mb" in df.columns:
                fig, axes = plt.subplots(1, 2, figsize=(10, 3))
                axes[0].plot(df["elapsed_s"], df["ram_mb"])
                axes[0].set_title("RAM (MB)"); axes[0].set_xlabel("Elapsed (s)")
                axes[1].plot(df["elapsed_s"], df.get("rst_mb", 0))
                axes[1].set_title("RST file (MB)"); axes[1].set_xlabel("Elapsed (s)")
                st.pyplot(fig)

    except Exception as e:
        st.error(f"Could not load diagnostics log: {e}")
else:
    st.info(
        f"No diagnostics log found at `{diag_csv}`.\n\n"
        "Start a simulation using the LiveDashboard from a notebook or script, "
        "then refresh this page."
    )

# ── Convergence tips ────────────────────────────────────────────────────────────
with st.expander("Convergence Troubleshooting Guide"):
    st.markdown("""
    | Symptom | Likely cause | Fix |
    |---------|-------------|-----|
    | Force residual not decreasing | Poor element quality or BC error | Check mesh quality (Page 3) |
    | Residual oscillating | Too large a load step | Increase max substeps |
    | MAPDL exits silently | Port conflict (zombie) | Go to Page 2 → Kill Zombies |
    | Diverged at first substep | Material instability or inverted elements | Check Jacobian |
    | Very slow convergence | Poorly conditioned stiffness (high aspect ratio) | Refine mesh |
    | STABILIZE energy > 5% | Too much artificial damping | Check if buckling or contact |
    | RST file growing > 10 GB | OUTRES,ALL,ALL with many substeps | Change to OUTRES,LAST or reduce max substeps |
    """)
