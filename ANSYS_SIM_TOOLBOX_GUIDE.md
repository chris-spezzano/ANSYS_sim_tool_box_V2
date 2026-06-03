# ANSYS Simulation Toolbox — Complete Reference Guide

> **For engineers and students who want to learn ANSYS MAPDL and AEDT
> simulation from first principles, understand the mathematics, and build
> reusable automated workflows.**

---

## Table of Contents

0. [Quick Start](#0-quick-start)
1. [Repository Map](#1-repository-map)
2. [Configuration System](#2-configuration-system)
3. [Resource Management & Zombie Cleanup](#3-resource-management--zombie-cleanup)
4. [Geometry Import](#4-geometry-import)
5. [Mesh Quality](#5-mesh-quality)
6. [Element Types](#6-element-types)
7. [Boundary Conditions — Mathematics](#7-boundary-conditions--mathematics)
8. [Solver Strategy](#8-solver-strategy)
9. [Live Diagnostics](#9-live-diagnostics)
10. [Results Post-Processing](#10-results-post-processing)
11. [HFSS / AEDT Workflow](#11-hfss--aedt-workflow)
12. [Multi-Physics Pipeline](#12-multi-physics-pipeline)
13. [Material Models](#13-material-models)
14. [Bug Catalogue](#14-bug-catalogue)
15. [Design Decisions](#15-design-decisions)
16. [Glossary](#16-glossary)

---

## 0  Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Kill zombie processes and verify ANSYS
python -c "from ams.resources.manager import kill_ansys_zombies, check_ports; kill_ansys_zombies(); print(check_ports())"

# 3. Launch the Streamlit app
streamlit run app.py

# 4. Or run a simulation directly from Python
python -c "
from ams.resources.manager import kill_ansys_zombies
from ams.mapdl.runner import MAPDLRunner
from ams.mapdl.solver import run_solution, SolverStrategy
from ams.mapdl.postproc import extract_results, save_plots
import yaml

kill_ansys_zombies()
cfg = yaml.safe_load(open('config.yaml'))
runner = MAPDLRunner(cfg)
mapdl  = runner.connect()
# ... (see notebooks for full workflow)
runner.disconnect()
"
```

---

## 1  Repository Map

```
ansys_sim_toolbox/
│
├── app.py                      # Streamlit home page (launch with: streamlit run app.py)
├── config.yaml                 # Master config — single source of truth
├── requirements.txt
├── ANSYS_SIM_TOOLBOX_GUIDE.md  # This file
│
├── ams/                        # Core Python package
│   ├── __init__.py             # Public API + version
│   │
│   ├── resources/
│   │   └── manager.py          # kill_ansys_zombies(), ResourceManager, check_ports()
│   │
│   ├── geometry/
│   │   ├── importer.py         # GeometryImporter: CDB/STL/STEP/parametric
│   │   ├── mesh_quality.py     # MeshQualityChecker: Jacobian, AR, manifold, watertight
│   │   └── element_selector.py # choose_element(), ELEMENT_LIBRARY reference
│   │
│   ├── mapdl/
│   │   ├── runner.py           # MAPDLRunner: connect/disconnect with zombie cleanup
│   │   ├── boundary.py         # apply_*: Dirichlet, Neumann, Robin, periodic, symmetry
│   │   ├── solver.py           # SolverStrategy, run_solution: NR/modal/harmonic/transient
│   │   ├── postproc.py         # extract_results, probe_point, save_plots, export_vtk
│   │   └── __init__.py
│   │
│   ├── hfss/
│   │   ├── runner.py           # HFSSRunner: connect with cleanup
│   │   ├── boundary.py         # assign_finite_conductivity, Floquet, periodic
│   │   ├── postproc.py         # extract_s_parameters, SE, energy partition
│   │   └── __init__.py
│   │
│   ├── materials/
│   │   ├── standard.py         # Elastic, BISO, MISO, Chaboche, Neo-Hookean, USERMAT
│   │   └── __init__.py
│   │
│   ├── diagnostics/
│   │   ├── dashboard.py        # LiveDashboard, live_solve_with_dashboard
│   │   └── __init__.py
│   │
│   └── multiphysics/
│       ├── pipeline.py         # SimulationPipeline, PipelineStage, sweep
│       └── __init__.py
│
├── pages/                      # Streamlit multi-page app
│   ├── 1_IO_Paths.py
│   ├── 2_Resources.py
│   ├── 3_Geometry.py
│   ├── 4_Boundary_Conditions.py
│   ├── 5_Solver.py
│   ├── 6_Diagnostics.py
│   ├── 7_Results.py
│   └── 8_Pipeline.py
│
├── notebooks/                  # Jupyter teaching notebooks (full math + code)
│   ├── 00_overview_and_setup.ipynb
│   ├── 01_io_and_config.ipynb
│   ├── 02_resource_management.ipynb
│   ├── 03_geometry_import_and_mesh_quality.ipynb
│   ├── 04_boundary_conditions.ipynb
│   ├── 05_solver_selection_and_strategy.ipynb
│   ├── 06_live_diagnostics.ipynb
│   ├── 07_results_and_visualization.ipynb
│   ├── 08_multiphysics_pipeline.ipynb
│   └── 09_custom_material_models.ipynb
│
├── docs/
│   ├── MAPDL_SOLVER_REFERENCE.md
│   ├── AEDT_HFSS_REFERENCE.md
│   ├── BOUNDARY_CONDITIONS_MATH.md
│   └── ELEMENT_TYPE_GUIDE.md
│
├── smoke_tests/
│   ├── test_resources.py
│   ├── test_mesh_quality.py
│   └── test_pipeline.py
│
└── examples/
    ├── tensile_bar/
    ├── cyclic_fatigue/
    ├── origami_folding/
    └── em_shielding/
```

---

## 2  Configuration System

All parameters are in `config.yaml`.  It is the single source of truth.

### Structure

```yaml
problem:
  name: "plate_with_hole"
  physics: "structural"   # structural | thermal | harmonic | coupled

mapdl:
  start_instance: true    # false = connect to running instance
  port: 50052
  ram_mb: 2048            # pre-allocated working memory
  nproc: 1                # cores (>1 requires HPC license)

geometry:
  source: "parametric"    # parametric | cdb | stl | step
  cdb_path: null          # absolute path when source == cdb

elements:
  type: "SOLID186"        # see §6 for full reference
  keyopt: {k2: 0}         # KEYOPT overrides

materials:
  - mat_id: 1
    name: "steel"
    model: "elastic"      # elastic | bilinear_plastic | chaboche | neohookean | usermat
    E_Pa: 200.0e9
    nu: 0.30

bcs:
  constraints:
    - {type: "fixed", axis: "X", side: "min"}
  loads:
    - {type: "pressure", axis: "X", side: "max", value_Pa: -100e6}

solver:
  type: "static"          # static | modal | harmonic | transient | buckling
  nlgeom: false
  nropt: "FULL"           # FULL | MODI | INIT | UNSYM
  lnsrch: true
  cnvtol_force: 0.005     # 0.5% force residual tolerance

resources:
  max_ram_mb: 16384
  max_nproc: 4

output:
  dir: "outputs"
  export_csv: true
  export_vtk: true
```

### Loading in Python

```python
import yaml
with open("config.yaml", encoding="utf-8") as fh:
    cfg = yaml.safe_load(fh)
```

---

## 3  Resource Management & Zombie Cleanup

### Why zombies occur

When a Python script crashes (Ctrl-C, kernel restart, power outage), the
`ansys252.exe` backend process keeps running.  It holds:
- A gRPC port (default 50052) — blocks next `launch_mapdl()` call
- An ANSYS license token — blocks new sessions on single-user license
- RAM — pre-allocated with `-m` flag, not released until process dies

### How to fix

```python
from ams.resources.manager import kill_ansys_zombies, check_ports

# 1. Check what's running (dry run — does not kill)
found = kill_ansys_zombies(dry_run=True)
print(f"Found {len(found)} ANSYS processes")

# 2. Kill them
kill_ansys_zombies(dry_run=False)

# 3. Verify ports are free
status = check_ports()
occupied = [p for p, s in status.items() if s]
print(f"Still occupied: {occupied}")  # should be empty
```

### RAM estimation

```python
from ams.resources.manager import estimate_memory

mem = estimate_memory(n_elements=50_000)
print(f"Conservative: {mem['conservative_mb']} MB")
# Set this as ram_mb in config.yaml
```

Rule of thumb: `ram_mb ≈ 25 × (n_elements / 1000)` MB.

---

## 4  Geometry Import

### CDB from nTopology

```python
from ams.geometry.importer import GeometryImporter
gi = GeometryImporter(mapdl)
gi.from_cdb("results/geometry/origami_mesh.cdb")

# CRITICAL: reassign element type if nTop exported SOLID185 for a shell model
gi.reassign_element_type("SHELL181", section_thickness_m=0.001)
```

**Why `reassign_element_type` is needed:** nTopology exports SOLID185 (3D
solid) by default.  For thin-shell structures (origami, sheet metal), this
causes severe **shear locking** — the element is too stiff in bending.
SHELL181 uses a proper Mindlin-Reissner shell formulation.

**Why `nrotat_all=True` (default):** nTopology may include coordinate system
rotations for nodes.  `NROTAT,ALL` resets all nodal coordinate systems to
align with the global Cartesian frame.  Without this, `D,ALL,UX,0` may
constrain the wrong direction on rotated nodes.

### Parametric geometry

```python
gi.build_plate_with_hole(
    width_m=0.10, height_m=0.10, depth_m=0.005, hole_r_m=0.010
)
# Kirsch Kt = 3.0 for this geometry → use as benchmark
```

---

## 5  Mesh Quality

Always run before solving:

```python
from ams.geometry.mesh_quality import MeshQualityChecker, QualityThresholds

checker = MeshQualityChecker(mapdl, QualityThresholds(
    aspect_ratio_max  = 20.0,
    jacobian_min      = 0.0,
    warping_max_deg   = 30.0,
))
report = checker.check(raise_on_fail=True)
report.print_summary()
```

### Critical metrics

| Metric | Good | Warning | Fatal |
|--------|------|---------|-------|
| Aspect ratio | < 5 | 5–20 | > 20 |
| Jacobian | > 0.5 | 0–0.5 | ≤ 0 |
| Warping (shells) | < 10° | 10–30° | > 30° |

**Negative Jacobian = inverted element = solver crash.**  Fix by checking
geometry import (STL winding, non-manifold faces) or refining the mesh around
sharp features.

---

## 6  Element Types

Quick reference:

| Element | Dim | Nodes | Best for |
|---------|-----|-------|----------|
| PLANE182 | 2D | 4 | Plane stress/strain/axisymmetric (fast) |
| PLANE183 | 2D | 8 | High-accuracy 2D with curved boundaries |
| SOLID185 | 3D | 8 | General 3D structural (most robust) |
| SOLID186 | 3D | 20 | High-accuracy 3D (curved surfaces) |
| SOLID187 | 3D | 10 | Complex CAD (auto-meshable tet) |
| SHELL181 | 3D | 4 | Thin shells + large rotation (origami) |
| SHELL281 | 3D | 8 | High-accuracy shells (< 20° rotation) |
| BEAM188  | 3D | 2 | Slender beams, all section types |

Use `choose_element()` for guided selection:

```python
from ams.geometry.element_selector import choose_element
elem = choose_element(spatial_dim=3, is_thin_shell=True, large_deformation=True)
print(elem.name)  # → SHELL181
```

---

## 7  Boundary Conditions — Mathematics

### Strong form

The elasticity PDE:

$$\nabla \cdot \boldsymbol{\sigma} + \mathbf{b} = \rho \ddot{\mathbf{u}} \quad \text{in } \Omega$$

Boundary conditions:

| Type | Equation | Physical meaning |
|------|----------|-----------------|
| Dirichlet | $\mathbf{u} = \bar{\mathbf{u}}$ on $\Gamma_D$ | Fixed wall, prescribed motion |
| Neumann | $\boldsymbol{\sigma} \cdot \mathbf{n} = \mathbf{t}$ on $\Gamma_N$ | Traction, pressure |
| Robin | $\boldsymbol{\sigma} \cdot \mathbf{n} + k_s \mathbf{u} = 0$ on $\Gamma_R$ | Elastic foundation |
| Periodic | $\mathbf{u}(\mathbf{x}+\mathbf{L}) = \mathbf{u}(\mathbf{x})$ | Unit cell |

### ANSYS pressure sign convention

ANSYS positive pressure = compressive.  For tensile traction:
```python
apply_neumann_pressure(mapdl, "face", "X", x_max, pressure_Pa=-100e6)
# Negative = tensile (pulling away from face)
```

### Periodic BCs in MAPDL

Implemented via CP (coupled DOF set) — pairs nodes on opposite faces so their
DOFs are equal.  **Requires matching mesh on both periodic faces** (same node
positions in the transverse directions).

```python
from ams.mapdl.boundary import apply_periodic
apply_periodic(mapdl, axis="X", lo_coord=0.0, hi_coord=0.02, dofs=["UX","UY","UZ"])
```

---

## 8  Solver Strategy

### Newton-Raphson algorithm

At each increment the equilibrium residual is:
$$\mathbf{R}(\mathbf{u}) = \mathbf{F}^{\text{int}}(\mathbf{u}) - \mathbf{F}^{\text{ext}} = \mathbf{0}$$

NR iteration:
$$[K_T(\mathbf{u}^k)] \Delta\mathbf{u}^k = -\mathbf{R}(\mathbf{u}^k)$$
$$\mathbf{u}^{k+1} = \mathbf{u}^k + \Delta\mathbf{u}^k$$

### NROPT variants

| Variant | Tangent update | Convergence | Use when |
|---------|---------------|-------------|----------|
| FULL | Every iteration | Quadratic | Strong nonlinearity |
| MODI | Once per substep | Linear | Mild nonlinearity |
| INIT | Never (use elastic K) | Sub-linear | Fallback |
| UNSYM | Full unsymmetric | Quadratic | Follower forces |

### Quick setup

```python
from ams.mapdl.solver import SolverStrategy, run_solution

strategy = SolverStrategy(
    type            = "static",
    nlgeom          = True,
    nsubsteps_initial = 20,
    nsubsteps_max   = 200,
    nropt           = "FULL",
    lnsrch          = True,
    neqit           = 25,
    cnvtol_force    = 0.005,
)
run_solution(mapdl, strategy)
```

### Retry ladder

When NR fails to converge:
1. AUTOTS bisects the load step (always on)
2. STABILIZE adds artificial energy damping
3. ARCLEN activates arc-length method (snap-through)
4. Two-stage load split (solve 50%, then 100%)

---

## 9  Live Diagnostics

```python
from ams.diagnostics.dashboard import LiveDashboard, live_solve_with_dashboard

# Option A: background monitoring
db = LiveDashboard(mapdl, poll_interval_s=3.0, output_dir="outputs")
db.start()
mapdl.solve()
db.stop()
db.print_summary()
db.export_csv()

# Option B: rich terminal display (requires pip install rich)
from ams.mapdl.solver import SolverStrategy
strategy = SolverStrategy.from_config(cfg)
live_solve_with_dashboard(mapdl, strategy)
```

What it monitors:
- gRPC port status (50052+)
- ANSYS process PID, RAM, CPU
- Current substep and NR iteration
- Force/displacement residuals vs tolerance
- RST file size

---

## 10  Results Post-Processing

```python
from ams.mapdl.postproc import extract_results, write_csv, save_plots, probe_point, export_vtk

# Extract fields
results = extract_results(mapdl, [
    "displacement_norm",
    "von_mises",
    "displacement_x", "displacement_y", "displacement_z",
    "principal_1", "principal_2", "principal_3",
])

# Export
write_csv(results, "outputs/run1/")
save_plots(mapdl, results, "outputs/run1/")
export_vtk(mapdl, "outputs/run1/")   # for ParaView

# Probe a point
vals = probe_point(mapdl, x=0.05, y=0.01, z=0.0,
                   quantities=["von_mises", "displacement_norm"])
print(f"von Mises at probe: {vals['von_mises']/1e6:.1f} MPa")
```

### Available field names

| Field name | MAPDL component | Units |
|------------|----------------|-------|
| `displacement_x/y/z` | UX/UY/UZ | m |
| `displacement_norm` | USUM | m |
| `stress_x/y/z` | SX/SY/SZ | Pa |
| `stress_xy/yz/xz` | SXY/SYZ/SXZ | Pa |
| `von_mises` | SEQV | Pa |
| `principal_1/2/3` | S1/S2/S3 | Pa |
| `temperature` | TEMP | K |

---

## 11  HFSS / AEDT Workflow

### Critical rules (from origami debug log)

1. **Always `non_graphical=True`** — GUI hangs in automated/batch mode
2. **Always `new_desktop=True`** — avoids stale setup state from prior runs
3. **Always delete project files before launch** — `cleanup_hfss_project()`
4. **Kill AEDT zombies first** — `kill_ansys_zombies(include_aedt=True)`
5. **STL import: use `import_free_surfaces=True`** — thin sheets fail otherwise
6. **Delete `_Unnamed_6` objects** — non-manifold cleanup artifacts that block meshing

```python
from ams.hfss.runner import HFSSRunner
from ams.hfss.boundary import assign_finite_conductivity, assign_floquet_port
from ams.hfss.postproc import extract_s_parameters, save_sparameter_plots

runner = HFSSRunner(cfg)
hfss   = runner.connect(kill_zombies=True)   # handles cleanup automatically

# Import geometry
hfss.modeler.import_3d_cad(stl_path, import_free_surfaces=True)
# Clean up non-manifold helpers
for name in list(hfss.modeler.objects.keys()):
    if name.endswith("_Unnamed_6"):
        hfss.modeler.delete(name)

# Assign BCs and solve
assign_finite_conductivity(hfss, "origami_body", conductivity_S_m=5.8e7)
assign_floquet_port(hfss, "AirBox", "AirBox", n_modes=8)
hfss.analyze()

# Extract results
results = extract_s_parameters(hfss)
save_sparameter_plots(results, "outputs/em/")
runner.disconnect()
```

---

## 12  Multi-Physics Pipeline

```python
from ams.multiphysics.pipeline import (
    SimulationPipeline,
    make_mapdl_structural_stage,
    make_hfss_em_stage,
)

# Single run
pipeline = SimulationPipeline(
    stages     = [make_mapdl_structural_stage(), make_hfss_em_stage()],
    global_cfg = cfg,
    output_dir = "outputs/run_001",
)
results = pipeline.run()

# Parametric sweep
sweep_results = pipeline.sweep([
    {"geometry.plate.hole_radius_m": 0.010},
    {"geometry.plate.hole_radius_m": 0.015},
    {"geometry.plate.hole_radius_m": 0.020},
])
```

Stage outputs are accessible as `results["stage_name"]["output_key"]`.

---

## 13  Material Models

| Model | Function | Required parameters |
|-------|----------|---------------------|
| Elastic | `assign_elastic` | E_Pa, nu, density |
| Bilinear plastic | `assign_bilinear_plastic` | + yield_stress, tangent_mod |
| Multilinear plastic | `assign_multilinear_plastic` | + [(strain, stress)...] |
| Chaboche | `assign_chaboche` | + [C_k], [γ_k], Q, b |
| Neo-Hookean | `assign_neohookean` | μ_Pa, d1_Pa |
| USERMAT | TB,USER + DLL | Custom Fortran |

Config-driven dispatch (no code changes needed):

```yaml
materials:
  - mat_id: 1
    model: "bilinear_plastic"
    E_Pa: 200.0e9
    nu: 0.30
    density_kg_m3: 7850
    plasticity:
      yield_stress_Pa: 250.0e6
      tangent_modulus_Pa: 2.0e9
```

---

## 14  Bug Catalogue

Documented bugs from the origami EMI workflow and MAPDL projects:

### BUG-01: nTopology CDB with SOLID185 for shell structures
**Symptom:** Extremely stiff response in bending, unphysical results.  
**Root cause:** nTop exports SOLID185 by default; thin sheets need SHELL181.  
**Fix:** `gi.reassign_element_type("SHELL181", section_thickness_m=t)`

### BUG-02: Nodal coordinate system mismatch after CDB import
**Symptom:** Applying UX=0 fixes the wrong direction (not global X).  
**Root cause:** nTop writes NBLOCK with coordinate system rotations.  
**Fix:** Call `mapdl.nrotat("ALL")` immediately after `mapdl.cdread()`.  
`GeometryImporter.from_cdb()` does this by default (`nrotat_all=True`).

### BUG-03: Port 50052 occupied by zombie
**Symptom:** `launch_mapdl()` fails with `WinError 10048` or hangs indefinitely.  
**Fix:** `kill_ansys_zombies()` then `check_ports()` before launching.

### BUG-04: HFSS stale project files
**Symptom:** DrivenModal setup registration fails; "setup already exists" error.  
**Root cause:** `.aedtresults/` contains adaptive pass counter from prior run.  
**Fix:** `cleanup_hfss_project(project_dir, project_name)` before launching HFSS.

### BUG-05: HFSS `_Unnamed_6` non-manifold object blocks meshing
**Symptom:** HFSS mesh generation fails with "non-manifold geometry" error.  
**Root cause:** `import_3d_cad(import_free_surfaces=True)` creates cleanup helpers.  
**Fix:** Delete all objects ending in `_Unnamed_6` after STL import.

### BUG-06: SHELL281 with large rotations
**Symptom:** SHELL281 gives wrong results for fold angles > 20°.  
**Root cause:** SHELL281 uses a higher-order kinematic description that breaks at large rotation.  
**Fix:** Use SHELL181 for origami / sheet forming (large rotation capable).

### BUG-07: nropt=FULL with STABILIZE and ARCLEN
**Symptom:** Solver fails to register the ARCLEN step properly.  
**Root cause:** ARCLEN manages its own step size; AUTOTS conflicts with it.  
**Fix:** Set `autots=False` when `arclen=True`.

### BUG-08: Periodic BC mesh mismatch
**Symptom:** `apply_periodic()` raises ValueError about mismatched node counts.  
**Root cause:** The mesh on the lo-face and hi-face have different node positions.  
**Fix:** Use `MSHKEY,1` (mapped meshing) or `LESIZE` to ensure face-matched meshes.

### BUG-09: RST file growing to > 10 GB
**Symptom:** Disk full during long parametric sweep.  
**Root cause:** `OUTRES,ALL,ALL` stores every substep with max substeps=1000.  
**Fix:** Use `OUTRES,LAST,ALL` for production runs; `OUTRES,ALL,ALL` only for debugging.

### BUG-10: `buffer_rgba()` vs `tostring_rgb()` in matplotlib 3.8+
**Symptom:** `AttributeError: FigureCanvasAgg has no attribute tostring_rgb`.  
**Root cause:** matplotlib 3.8 removed `tostring_rgb()`.  
**Fix:** Use `fig.canvas.buffer_rgba()` then slice `[:,:,:3]` (implemented in `postproc.py`).

---

## 15  Design Decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| YAML config (not argparse) | Reproducible, shareable, no code changes | Slightly more verbose than CLI flags |
| kill_zombies before launch | Prevents port conflicts that are hard to debug | Kills processes — confirm dry_run first |
| Mesh quality gate | Blocks the solve on fatal quality issues | Strict mode; disable `raise_on_fail` if needed |
| MAPDLRunner (not bare launch_mapdl) | Encapsulates zombie cleanup, port check, ANS_USER_PATH | Slightly more abstraction |
| Diagnostic background thread | Non-blocking monitoring during long solves | Thread safety: read-only queries only |
| Pipeline checkpoints | Resume from a failed stage without re-running completed stages | JSON-only (numpy arrays are serialized as strings) |
| Factory functions (make_*_stage) | Ready-to-use standard stages | Less flexible than custom `run_fn` for unusual problems |

---

## 16  Glossary

| Term | Definition |
|------|-----------|
| **APDL** | ANSYS Parametric Design Language — ANSYS's built-in scripting language |
| **AEDT** | ANSYS Electronics Desktop — umbrella application for HFSS, Maxwell, etc. |
| **AR** | Aspect ratio — longest/shortest edge ratio of an element |
| **AUTOTS** | Automatic time stepping — bisects load step on divergence |
| **CDB** | ANSYS CDWRITE database file — full FE model dump (used by nTopology) |
| **DOF** | Degree of freedom — nodal unknown (UX, UY, UZ, ROTX, TEMP, ...) |
| **gRPC** | Remote Procedure Call protocol used by PyMAPDL/PyAEDT to control ANSYS |
| **HFSS** | High-Frequency Structural Simulator — ANSYS EM solver |
| **Jacobian** | Determinant of the isoparametric mapping matrix; < 0 = inverted element |
| **KEYOPT** | Element-specific option integer; controls integration scheme, formulation |
| **MAPDL** | Mechanical APDL — the underlying ANSYS structural solver |
| **NR** | Newton-Raphson — iterative algorithm for solving nonlinear equations |
| **NLGEOM** | Nonlinear geometry flag — enables large-deformation kinematics |
| **NROPT** | NR option: FULL (reassemble each iteration) / MODI / INIT |
| **PostProc** | Post-processing — reading and visualizing results from the RST file |
| **RST** | ANSYS result file — stores all computed fields for all result sets |
| **RVE** | Representative Volume Element — unit cell for homogenization |
| **SE** | Shielding Effectiveness = -20 log₁₀\|S21\| (dB) |
| **SEQV** | ANSYS identifier for von Mises equivalent stress |
| **STABILIZE** | Artificial energy damping to pass local instabilities (Level 2 retry) |
| **USUM** | Total displacement magnitude = √(UX² + UY² + UZ²) |
| **USERMAT** | Custom Fortran subroutine for user-defined constitutive model |
| **Zombie** | Stale ANSYS process holding a port after a script crash |

---

*ANSYS Simulation Toolbox v1.0 — Built on lessons from the origami EMI workflow
(`D:/Projects/origami_emi_workflow`) and the epithelial MAPDL toolbox
(`D:/Projects/MAPDL`). Designed to match the depth and pedagogy of the NCM
toolbox (`E:/Projects/me227_project_A/ncm_toolbox`).*
