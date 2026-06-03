"""Page 7 — Results: visualize and export simulation outputs."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="Results", layout="wide")
st.title("Step 7 · Results Viewer")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh: return yaml.safe_load(fh)
    return {}

cfg = _load_cfg()
out_dir = Path(cfg.get("output", {}).get("dir", "outputs"))

# ── Available result files ─────────────────────────────────────────────────────
st.subheader("Available Results")
csv_files = list(out_dir.rglob("nodal_results.csv")) + list(out_dir.rglob("emi_results.csv"))
vtk_files  = list(out_dir.rglob("*.vtk"))
png_files  = list(out_dir.rglob("*.png"))
gif_files  = list(out_dir.rglob("*.gif"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("CSV files",  len(csv_files))
c2.metric("VTK files",  len(vtk_files))
c3.metric("PNG images", len(png_files))
c4.metric("GIF animations", len(gif_files))

# ── Field selection ────────────────────────────────────────────────────────────
tab_struct, tab_em, tab_animate = st.tabs(["Structural Fields", "EM Results", "Animation"])

with tab_struct:
    st.subheader("Structural Field Viewer")

    if csv_files:
        selected_csv = st.selectbox("Select CSV", csv_files,
                                     format_func=lambda p: str(p.relative_to(out_dir)))
        try:
            import pandas as pd
            df = pd.read_csv(selected_csv)
            st.caption(f"{len(df)} nodes, columns: {list(df.columns)}")

            numeric_cols = [c for c in df.columns if c != "node_index"]
            field = st.selectbox("Field to plot", numeric_cols)

            col1, col2 = st.columns(2)
            with col1:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                fig, ax = plt.subplots(figsize=(7, 4))
                ax.hist(df[field].dropna(), bins=50, edgecolor="k", linewidth=0.4)
                ax.set_xlabel(field.replace("_"," "))
                ax.set_ylabel("Node count")
                ax.set_title(f"Distribution of {field}")
                ax.grid(True, alpha=0.3)
                st.pyplot(fig)
                plt.close(fig)

            with col2:
                st.metric(f"Max {field}", f"{df[field].max():.4g}")
                st.metric(f"Min {field}", f"{df[field].min():.4g}")
                st.metric(f"Mean {field}", f"{df[field].mean():.4g}")

            st.download_button(
                "Download CSV",
                data=open(selected_csv, "rb").read(),
                file_name=selected_csv.name,
                mime="text/csv",
            )
        except Exception as e:
            st.error(f"Error loading CSV: {e}")
    else:
        st.info("No results CSV files found.  Run a simulation first.")

    # PNG viewer
    st.subheader("Saved Plots")
    if png_files:
        sel_png = st.selectbox("Select plot", png_files,
                                format_func=lambda p: str(p.relative_to(out_dir)))
        st.image(str(sel_png), use_container_width=True)
    else:
        st.info("No PNG files found.")

with tab_em:
    st.subheader("EMI Shielding Results")
    em_csvs = list(out_dir.rglob("emi_results.csv"))
    if em_csvs:
        sel = st.selectbox("Select EMI result", em_csvs,
                            format_func=lambda p: str(p.relative_to(out_dir)))
        try:
            import pandas as pd
            import matplotlib.pyplot as plt
            df = pd.read_csv(sel)

            fig, axes = plt.subplots(1, 2, figsize=(12, 4))
            axes[0].plot(df["freq_GHz"], df["SE_dB"], "b-", linewidth=1.5)
            axes[0].set_xlabel("Frequency (GHz)"); axes[0].set_ylabel("SE (dB)")
            axes[0].set_title("Shielding Effectiveness"); axes[0].grid(True, alpha=0.3)

            axes[1].fill_between(df["freq_GHz"], 0, df["R"], alpha=0.6, label="R")
            axes[1].fill_between(df["freq_GHz"], df["R"], df["R"]+df["T"], alpha=0.6, label="T")
            axes[1].fill_between(df["freq_GHz"], df["R"]+df["T"], 1, alpha=0.6, label="A")
            axes[1].set_xlabel("Frequency (GHz)"); axes[1].set_ylabel("Energy fraction")
            axes[1].set_title("R + T + A = 1"); axes[1].legend(); axes[1].grid(True, alpha=0.3)
            st.pyplot(fig); plt.close(fig)

            c1, c2, c3 = st.columns(3)
            c1.metric("Peak SE", f"{df['SE_dB'].max():.1f} dB")
            c2.metric("Mean SE", f"{df['SE_dB'].mean():.1f} dB")
            c3.metric("Freq at peak SE", f"{df.loc[df['SE_dB'].idxmax(),'freq_GHz']:.1f} GHz")
        except Exception as e:
            st.error(f"Error: {e}")
    else:
        st.info("No EMI results found.  Run the HFSS stage first.")

with tab_animate:
    st.subheader("Animations")
    if gif_files:
        sel_gif = st.selectbox("Select animation", gif_files,
                                format_func=lambda p: str(p.relative_to(out_dir)))
        st.image(str(sel_gif))
    else:
        st.info("No GIF animations found.  Use save_animation() in a notebook.")
