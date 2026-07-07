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
5. [nTopology Automation & Parameter Injection](#5-ntopology-automation--parameter-injection)
6. [Mesh Quality](#6-mesh-quality)
7. [Element Types](#7-element-types)
8. [Boundary Conditions — Mathematics](#8-boundary-conditions--mathematics)
9. [Origami Fold Boundary Conditions](#9-origami-fold-boundary-conditions)
10. [Solver Strategy](#10-solver-strategy)
11. [Live Diagnostics](#11-live-diagnostics)
12. [Results Post-Processing](#12-results-post-processing)
13. [HFSS / AEDT Workflow](#13-hfss--aedt-workflow)
14. [Multi-Physics Pipeline](#14-multi-physics-pipeline)
15. [Material Models](#15-material-models)
16. [Bug Catalogue](#16-bug-catalogue)
17. [Design Decisions](#17-design-decisions)
18. [Glossary](#18-glossary)

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
│   │   ├── importer.py         # GeometryImporter: CDB/INP/STL/STEP/parametric
│   │   ├── ntop_driver.py      # NTopDriver: headless CLI + JSON parameter injection
│   │   ├── mesh_quality.py     # MeshQualityChecker: Jacobian, AR, manifold, watertight
│   │   └── element_selector.py # choose_element(), ELEMENT_LIBRARY reference
│   │
│   ├── mapdl/
│   │   ├── runner.py           # MAPDLRunner: connect/disconnect with zombie cleanup
│   │   ├── boundary.py         # apply_*: Dirichlet, Neumann, Robin, periodic, symmetry
│   │   ├── origami_bcs.py      # apply_waterbomb_fold_bcs: crease-line BC assignment
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
│       ├── pipeline.py         # SimulationPipeline, PipelineStage, build_waterbomb_pipeline
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
├── simulation_meshes/          # Manually exported meshes (committed for quick testing)
│   └── waterbomb_mesh.inp      # Abaqus .inp from nTopology Export FE Mesh block
│
└── examples/
    ├── tensile_bar/            # Kirsch benchmark — Kt=3 stress concentration
    ├── cyclic_fatigue/         # Fatigue life estimation
    ├── origami_folding/        # Waterbomb fold — nTop→MAPDL→HFSS full pipeline
    │   ├── origami_folding.yaml
    │   └── (generated outputs in outputs/origami_folding/)
    ├── waterbomb_sweep/        # Parametric sweep over trough depth × fold angle
    │   ├── waterbomb_sweep.yaml
    │   └── run_sweep.py
    └── em_shielding/           # HFSS EM shielding standalone example
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

### nTopology 5.x — Abaqus .inp export (current workflow)

nTopology 5.x does **not** support `.cdb` export from the Export FE Mesh block.
The supported format for FEA is **Abaqus `.inp`**.  The toolbox converts it
transparently using `meshio` before MAPDL ever sees it.

**Step 1 — In nTopology:**
- Add an FE Shell Mesh block, connect it to your final body
- In the Export FE Mesh block, set Path to a full absolute path ending in `.inp`:
  ```
  E:\Projects\ansys_sim_toolbox\simulation_meshes\waterbomb_mesh.inp
  ```
- Compute the Export FE Mesh block — the file is written immediately.

**Step 2 — In Python:**

```python
from ams.geometry.importer import GeometryImporter

gi = GeometryImporter(mapdl)

# Converts .inp → .cdb via meshio, then imports with CDREAD
gi.from_inp(
    "E:/Projects/ansys_sim_toolbox/simulation_meshes/waterbomb_mesh.inp",
    reassign_et="SHELL181",      # nTop shell mesh → SHELL181 for large deformation
)
```

**Step 3 — In YAML (for pipeline use):**

```yaml
geometry:
  source: "inp"
  inp_path: "E:/Projects/ansys_sim_toolbox/simulation_meshes/waterbomb_mesh.inp"
  cdb_path: null
```

The `build_waterbomb_pipeline()` factory reads `geometry.inp_path` automatically.

### How the .inp → .cdb conversion works

```
nTopology Export FE Mesh
  └─ writes waterbomb_mesh.inp  (Abaqus format: *NODE, *ELEMENT, *SURFACE sections)
         │
         ▼  meshio.read()
  meshio internal representation
  (points array, cells list, tags dict)
         │
         ▼  meshio.write(format="ansys")
  waterbomb_mesh.cdb  (ANSYS CDB: NBLOCK, EBLOCK, CMBLOCK sections)
         │
         ▼  mapdl.cdread("DB", ...)
  MAPDL mesh database
         │
         ▼  reassign_element_type("SHELL181")
  SHELL181 elements ready for large-deformation solve
```

The `.cdb` is written alongside the `.inp` (same directory) and reused on
subsequent runs.  Delete it to force re-conversion.

### Legacy: CDB from older nTopology versions

If you have nTopology < 5.0 or a pre-existing `.cdb`:

```python
gi.from_cdb("path/to/mesh.cdb")
gi.reassign_element_type("SHELL181", section_thickness_m=0.001)
```

**Why `reassign_element_type` is needed:** nTopology exports SOLID185 (3D
solid) by default.  For thin-shell structures (origami, sheet metal), this
causes severe **shear locking** — the element is too stiff in bending.
SHELL181 uses a Mindlin-Reissner shell formulation with large-rotation capability.

**Why `nrotat_all=True` (default):** nTopology may include coordinate system
rotations for nodes.  `NROTAT,ALL` resets all nodal coordinate systems to
align with the global Cartesian frame.  Without this, `D,ALL,UX,0` may
constrain the wrong direction on rotated nodes.

### Parametric geometry (no nTopology required)

```python
gi.build_plate_with_hole(
    width_m=0.10, height_m=0.10, depth_m=0.005, hole_r_m=0.010
)
# Kirsch Kt = 3.0 for this geometry → use as benchmark
```

---

## 5  nTopology Automation & Parameter Injection

### Overview

`ams/geometry/ntop_driver.py` drives nTopology headlessly from Python.
Any **Input Block** visible in the nTopology workflow tree can be overridden
at run time by passing a JSON file to the CLI:

```
ntopology.exe --headless --run Waterbomb.ntop
              --json-input _ntop_params.json
              --output outputs/geometry/
```

### JSON parameter file format

The JSON file maps Input Block names (exactly as shown in the tree) to new values:

```json
{
  "inputs": {
    "Plate Size X":    70.0,
    "Plate Size Y":    70.0,
    "Plate Thickness":  3.0,
    "Trough Depth":     1.6,
    "Trough Width":     2.0,
    "Mesh Tolerance":   1.0
  }
}
```

Units are whatever the Input Block is defined in nTopology (the nTop workflow
defines the unit; the JSON value is a bare number).  For the Waterbomb workflow
all blocks are defined in **mm**.

### Python API

```python
from ams.geometry.ntop_driver import NTopDriver

driver = NTopDriver()   # auto-detects ntopology.exe
outputs = driver.run(
    project    = "Waterbomb.ntop",
    parameters = {
        "Plate Size X":  70.0,
        "Trough Depth":   2.4,   # deeper crease → lower fold force
        "Mesh Tolerance": 0.5,   # finer mesh → longer nTop run
    },
    export_dir       = "outputs/geometry/iter_001",
    expected_outputs = ["*.inp"],
)
cdb_path = outputs["*.inp"]
```

### YAML-driven (pipeline use)

```yaml
ntop:
  executable: null           # null = auto-detect ntopology.exe
  project: "Waterbomb.ntop"
  timeout_s: 300

  parameters:                # ← these become the JSON "inputs" dict
    Plate Size X:   70.0
    Plate Size Y:   70.0
    Plate Thickness: 3.0
    Trough Depth:    1.6
    Trough Width:    2.0
    Mesh Tolerance:  1.0

  export_dir: "outputs/origami_folding/geometry"
  expected_outputs: ["*.inp"]
```

### How YAML parameters connect to boundary conditions

The same parameter values that control nTop geometry must match the BC geometry
parameters.  The link is explicit:

| nTop Input Block | nTop effect | YAML BC parameter that must match |
|---|---|---|
| `Plate Size X` | overall plate width | `bcs.origami_fold.plate_length_mm` |
| `Plate Size X / 2` | crease x-centre | `bcs.origami_fold.plate_center_x_mm` |
| `Plate Size Y / 2` | crease y-centre | `bcs.origami_fold.plate_center_y_mm` |
| `Mesh Tolerance` | mesh edge length | `bcs.origami_fold.crease_tol_mm` (≥ Mesh Tolerance / 2) |
| `Trough Depth` | crease geometry | no direct BC link — affects stiffness only |

In a parametric sweep, when `Plate Size X` changes, update `plate_length_mm`
and `plate_center_x_mm` in the same sweep point dict.  `crease_tol_mm` should
also scale: use `Mesh Tolerance / 2` as the minimum value.

### Parametric sweep

```python
from ams.geometry.ntop_driver import NTopDriver

driver = NTopDriver()
results = driver.run_sweep(
    project          = "Waterbomb.ntop",
    param_sets       = [
        {"Trough Depth": 1.0, "Mesh Tolerance": 1.0},
        {"Trough Depth": 1.6, "Mesh Tolerance": 1.0},
        {"Trough Depth": 2.4, "Mesh Tolerance": 0.5},
    ],
    base_export_dir  = "outputs/trough_sweep",
    expected_outputs = ["*.inp"],
)
# results[0]["*.inp"] → Path to first iteration's .inp file
```

### Generalizing to other geometries

The `NTopDriver` is geometry-agnostic.  Any `.ntop` file that has:
1. **Input Blocks** for the parameters you want to vary
2. An **Export FE Mesh** block pointing to a relative `.inp` path

...can be driven by exactly the same Python API.  The only things that change:
- The `parameters` dict keys (must match your Input Block names)
- The `bcs.*` section (depends on your geometry's BC locations)

For non-origami geometries, use the standard `bcs.constraints` / `bcs.loads`
blocks (see §8) driven by face coordinates, instead of `bcs.origami_fold`.

---

## 6  Mesh Quality

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

## 7  Element Types

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

## 8  Boundary Conditions — Mathematics

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

## 9  Origami Fold Boundary Conditions

Origami simulations require BCs that target **crease lines**, not faces.
`ams/mapdl/origami_bcs.py` implements two strategies for the waterbomb pattern,
generalizable to any origami tessellation.

### Crease-line geometry for the waterbomb

For a square plate of side $L$ centred at $(c_x, c_y)$:

| Crease | Equation | MAPDL selection |
|--------|----------|-----------------|
| Vertical | $x = c_x$ | `np.abs(x - cx) < tol` |
| Horizontal | $y = c_y$ | `np.abs(y - cy) < tol` |
| +45° diagonal | $y - c_y = x - c_x$ | `np.abs((y-cy) - (x-cx)) < tol` |
| −45° diagonal | $y - c_y = -(x - c_x)$ | `np.abs((y-cy) + (x-cx)) < tol` |

The diagonal equations cannot be expressed with MAPDL's `NSEL,S,LOC` (which
only selects coordinate slabs).  The selection is computed in NumPy over all
node coordinates and the matching nodes are added one by one with `NSEL,A,NODE`.

### Strategy A — Displacement-driven (recommended)

1. Pin centre patch: `D,ALL,UX,0` + `D,ALL,UY,0` + `D,ALL,UZ,0`  
   (rotational DOFs left free — the dome hub must rotate)
2. Apply `D,ALL,UZ,δ` on the 4 outer corner nodes

Fold half-angle from corner displacement:
$$\theta = \arcsin\!\left(\frac{\delta}{L/2}\right)$$

For the 70 mm plate with `fold_uz_mm: 15`: $\theta \approx 25°$.

### Strategy B — Rotation-driven (SHELL181 only)

Prescribe rotational DOFs directly at each crease.
Mountain/valley folds are distinguished by sign:

| Crease | DOF | Sign | Fold type |
|--------|-----|------|-----------|
| Vertical | ROTY | + | valley |
| Horizontal | ROTX | + | valley |
| +45° diagonal | ROTZ | − | mountain |
| −45° diagonal | ROTZ | − | mountain |

### Named components vs coordinate selection

nTopology can export **Named Selections** (CMBLOCK records in the CDB) that
tag node groups by name.  When present, they are used directly:

```python
mapdl.cmsel("S", "CREASE_VERT")   # instant, exact
```

When absent (current default), the coordinate math above runs instead.  To
enable named components, add Named Selection export blocks in nTop for each
crease tag (`CREASE_VERT`, `CREASE_HORIZ`, `CREASE_DIAG_P`, `CREASE_DIAG_N`,
`CENTER_PATCH`, `OUTER_CORNERS`) and wire them to the Export FE Mesh `Sets`
field.  Then set the component names in the YAML:

```yaml
bcs:
  origami_fold:
    component_names:
      crease_vert:   "CREASE_VERT"
      crease_horiz:  "CREASE_HORIZ"
      crease_diag_p: "CREASE_DIAG_P"
      crease_diag_n: "CREASE_DIAG_N"
      center_patch:  "CENTER_PATCH"
      outer_corners: "OUTER_CORNERS"
```

### Python API

```python
from ams.mapdl.origami_bcs import apply_waterbomb_fold_bcs, get_crease_node_sets

# Apply all BCs from config
apply_waterbomb_fold_bcs(mapdl, cfg)

# Get crease node sets for post-processing
sets = get_crease_node_sets(mapdl, cx=0.035, cy=0.035, crease_tol_m=0.0006)
print(sets.keys())  # vertical, horizontal, diag_p, diag_n, all_creases
```

### Generalizing to other origami patterns

The approach extends to any pattern where crease lines have an analytic
description:

| Pattern | Crease description | NumPy condition |
|---|---|---|
| Miura-ori | Parallel diagonal lines | `np.abs((y - ky*x) - offset) < tol` |
| Yoshimura | Zigzag lines | `np.abs(y - f(x)) < tol` (piecewise) |
| Kresling | Helical lines | Distance from parametric helix < tol |
| Arbitrary | Named components from nTop | `mapdl.cmsel("S", name)` |

For any pattern: define the crease equation, compute the boolean mask in NumPy,
select nodes with `NSEL,A,NODE`, apply DOFs.  The `crease_tol_mm` parameter is
the only geometry-specific tuning value — set it to at least half the mesh
edge length.

---

## 10  Solver Strategy

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

## 11  Live Diagnostics

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

## 12  Results Post-Processing

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

## 13  HFSS / AEDT Workflow

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

## 14  Multi-Physics Pipeline

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

## 15  Material Models

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

## 16  Bug Catalogue

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

### BUG-11: nTopology 5.x Export FE Mesh does not support `.cdb`
**Symptom:** Export FE Mesh block shows error: *"Provided file extension (.cdb) isn't supported."*  
**Root cause:** nTopology 5.x removed native CDB export from the Export FE Mesh block.  
**Fix:** Set the Path to `waterbomb_mesh.inp` (Abaqus format).  Use `GeometryImporter.from_inp()`
which converts to CDB via meshio automatically.  See §4 and §5.

### BUG-12: `crease_tol_mm` too small — crease nodes not selected
**Symptom:** `apply_waterbomb_fold_bcs()` reports 0 crease nodes and the fold never initialises.  
**Root cause:** `crease_tol_mm` is smaller than the nTop mesh edge length, so no nodes fall
within the selection band around the crease line.  
**Fix:** Set `crease_tol_mm ≥ Mesh Tolerance / 2`.  For a 1 mm mesh tolerance use `crease_tol_mm: 0.6`.

### BUG-13: `pin_center_radius_mm` too small — rigid body mode
**Symptom:** Solver fails immediately with "singular stiffness matrix" or large initial displacement.  
**Root cause:** No nodes found within the centre-pin radius → the structure has no translation constraint.  
**Fix:** Increase `pin_center_radius_mm` (default 2.0 mm is appropriate for the 70 mm plate).
Verify by checking the print output: *"BCs: centre patch pinned — N nodes"*.  If N=0, increase the radius.

### BUG-14: meshio writes wrong element type (SHELL63 instead of SHELL181)
**Symptom:** `from_inp()` imports successfully but elements are SHELL63 — old-style overlay shell.  
**Root cause:** meshio maps nTopology's `triangle3` cells to MAPDL's SHELL63.  
**Fix:** Always call `gi.reassign_element_type("SHELL181", ...)` after `from_inp()`, or pass
`reassign_et="SHELL181"` directly to `from_inp()`.  This is handled automatically by
`build_waterbomb_pipeline()`.

---

## 17  Design Decisions

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

## 18  Glossary

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
