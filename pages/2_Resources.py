"""Page 2 — Resources: allocate CPU/RAM and kill zombie processes."""

import streamlit as st
import yaml
from pathlib import Path

st.set_page_config(page_title="Resources", layout="wide")
st.title("Step 2 · Computational Resources")

st.markdown("""
Before starting any simulation, check that:
1. No zombie ANSYS processes are holding ports or memory
2. The RAM allocation is appropriate for your mesh size
3. The correct port is selected (default 50052 for MAPDL)

**Why this matters:** A zombie MAPDL from a previous crashed run will block
port 50052, causing `launch_mapdl()` to fail silently or hang indefinitely.
""")

def _load_cfg():
    p = Path("config.yaml")
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    return {}

def _save_cfg(cfg):
    with open("config.yaml", "w", encoding="utf-8") as fh:
        yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

cfg = _load_cfg()

# ── System info ────────────────────────────────────────────────────────────────
st.subheader("System Resources")
if st.button("Scan System"):
    try:
        from ams.resources.manager import ResourceManager
        rm   = ResourceManager()
        info = rm.system_info(scan_ports=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Physical CPUs",    info.physical_cpus)
        c2.metric("Total RAM",        f"{info.total_ram_mb:,} MB")
        c3.metric("Available RAM",    f"{info.available_ram_mb:,} MB")
        c4.metric("ANSYS version",    info.ansys_version or "not found")

        occ  = {p: s for p, s in info.occupied_ports.items() if s}
        free = {p: s for p, s in info.occupied_ports.items() if not s}
        if occ:
            st.warning(f"Occupied ports: {list(occ.keys())} — run Kill Zombies first!")
        else:
            st.success(f"All ports free: {list(free.keys())}")

        st.session_state["system_info"] = info
    except Exception as e:
        st.error(f"Scan failed: {e}")

# ── Zombie cleanup ─────────────────────────────────────────────────────────────
st.subheader("Zombie Process Cleanup")
st.markdown("""
Zombie ANSYS processes are MAPDL or AEDT instances left running after a
crashed simulation.  They hold gRPC ports, license tokens, and RAM.
""")

col_dry, col_kill = st.columns(2)

with col_dry:
    if st.button("Dry Run (list only)", type="secondary"):
        try:
            from ams.resources.manager import kill_ansys_zombies
            found = kill_ansys_zombies(dry_run=True, verbose=False)
            if found:
                st.warning(f"Found {len(found)} ANSYS process(es):")
                for p in found:
                    st.code(f"PID {p['pid']:>8}  {p['name']:<20}  {p.get('cmdline','')[:60]}")
            else:
                st.success("No ANSYS processes found — system is clean.")
        except Exception as e:
            st.error(f"Error: {e}")

with col_kill:
    if st.button("Kill All Zombies", type="primary"):
        try:
            from ams.resources.manager import kill_ansys_zombies
            killed = kill_ansys_zombies(dry_run=False, include_aedt=True, verbose=False)
            n_killed = sum(1 for p in killed if p.get("killed"))
            if n_killed:
                st.success(f"Killed {n_killed} zombie process(es)")
            elif killed:
                st.warning(f"Found {len(killed)} processes but could not kill all (permission?)")
            else:
                st.info("No processes to kill")
        except Exception as e:
            st.error(f"Error: {e}")

# ── Resource recommendation ────────────────────────────────────────────────────
st.subheader("Recommended Settings")
n_elements = st.number_input(
    "Expected element count",
    min_value=100,
    max_value=10_000_000,
    value=10_000,
    step=1000,
    help=(
        "Rough element count for your mesh.  "
        "Used to estimate RAM requirements.\n"
        "Rule of thumb: 15–25 MB per 1000 elements."
    ),
)
has_hpc = st.checkbox(
    "ANSYS HPC license available",
    value=False,
    help="HPC license allows nproc > 1.  Without it, set nproc = 1.",
)

if st.button("Get Recommendation"):
    try:
        from ams.resources.manager import ResourceManager
        rm  = ResourceManager()
        rec = rm.recommend(n_elements=n_elements, has_hpc_license=has_hpc)

        c1, c2, c3 = st.columns(3)
        c1.metric("Recommended nproc",    rec.nproc)
        c2.metric("Recommended RAM (MB)", rec.ram_mb)
        c3.metric("Recommended port",     rec.mapdl_port)

        if rec.warnings:
            for w in rec.warnings:
                st.warning(w)

        st.info("**Why these values?**")
        for key, reason in rec.rationale.items():
            st.markdown(f"- **{key}**: {reason}")

        # Apply to config
        cfg.setdefault("resources", {})["max_nproc"] = rec.nproc
        cfg.setdefault("mapdl",     {})["ram_mb"]    = rec.ram_mb
        cfg.setdefault("mapdl",     {})["port"]      = rec.mapdl_port
        st.session_state["cfg"] = cfg

    except Exception as e:
        st.error(f"Error: {e}")

# ── Manual overrides ───────────────────────────────────────────────────────────
st.subheader("Manual Configuration")
mapdl_cfg = cfg.setdefault("mapdl", {})
res_cfg   = cfg.setdefault("resources", {})

c1, c2, c3 = st.columns(3)
with c1:
    mapdl_cfg["port"]   = st.number_input("MAPDL port",    value=int(mapdl_cfg.get("port", 50052)))
with c2:
    mapdl_cfg["ram_mb"] = st.number_input("RAM (MB)",       value=int(mapdl_cfg.get("ram_mb", 2048)))
with c3:
    res_cfg["max_nproc"]= st.number_input("Max CPUs",       value=int(res_cfg.get("max_nproc", 1)))

if st.button("Save Configuration", type="primary"):
    _save_cfg(cfg)
    st.success("Saved to config.yaml")
    st.session_state["cfg"] = cfg
