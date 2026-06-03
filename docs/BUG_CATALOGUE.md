# Bug Catalogue — ANSYS Simulation Toolbox

> A living record of real bugs encountered during development and use.
> Each entry includes the symptom, root cause, fix, and the file that implements it.
> Cross-referenced with the origami EMI workflow and MAPDL toolbox histories.

---

## BUG-01 — nTopology CDB exports SOLID185 for shell structures

**Status:** Fixed (default behaviour of `GeometryImporter.from_cdb`)  
**Symptom:** Thin-shell structure (origami copper sheet) is approximately 100× too stiff
in bending.  Displacement results are 1–2 orders of magnitude smaller than expected.  
**Root cause:** nTopology's mesh export always uses SOLID185 (3D 8-node hexahedron) by
default.  For thin-walled structures where thickness/span < 0.1, SOLID185 exhibits
severe **shear locking** — a numerical artefact where the element resists bending by
generating spurious transverse shear strains.  The correct element is SHELL181, which
uses a Mindlin-Reissner plate formulation with reduced integration to avoid locking.  
**Fix:** `GeometryImporter.from_cdb(path, reassign_et='SHELL181', section_thickness_m=t)`  
**Code:** [ams/geometry/importer.py](../ams/geometry/importer.py) — `reassign_element_type()`  
**Reference:** ANSYS Element Reference §14.181 (SHELL181 large-rotation formulation)

---

## BUG-02 — Nodal coordinate system mismatch after CDB import

**Status:** Fixed (default: `nrotat_all=True` in `from_cdb`)  
**Symptom:** Applying `mapdl.d('ALL', 'UX', 0)` constrains a different direction than
global X.  Symmetric-about-Y results show the wrong symmetry axis.  
**Root cause:** nTopology includes per-node coordinate system rotations in the NBLOCK
section of the CDB file.  After `CDREAD`, some nodes have their local CS rotated
relative to the global frame.  Applying `D,ALL,UX` constrains the **local** X, not
the global X.  
**Fix:** Call `mapdl.nrotat('ALL')` immediately after `mapdl.cdread()`.  This resets
all nodal coordinate systems to align with the global Cartesian frame.  
**Code:** [ams/geometry/importer.py](../ams/geometry/importer.py) — `from_cdb(nrotat_all=True)`  

---

## BUG-03 — Port 50052 occupied by zombie MAPDL process

**Status:** Mitigated (automatic zombie cleanup in `MAPDLRunner.connect`)  
**Symptom:**
```
OSError: [WinError 10048] Only one usage of each socket address is normally permitted.
```
or: `launch_mapdl()` hangs indefinitely without error.  
**Root cause:** When a Python kernel is restarted (Jupyter, Ctrl-C, power loss), the
`ansys252.exe` backend keeps running.  It holds port 50052 open.  The next
`launch_mapdl(port=50052)` cannot bind to the port.  
**Fix:** `kill_ansys_zombies(dry_run=False)` before any `launch_mapdl()` call.  
`MAPDLRunner.connect(kill_zombies=True)` does this automatically.  
**Code:** [ams/resources/manager.py](../ams/resources/manager.py) — `kill_ansys_zombies()`  
**Reference:** `D:/Projects/origami_emi_workflow/docs/origami_workflow_debug_log.md`

---

## BUG-04 — HFSS stale `.aedtresults` directory

**Status:** Fixed (automatic cleanup in `HFSSRunner.connect`)  
**Symptom:** `DrivenModal setup registration failed` or `Setup already exists` error when
launching HFSS for a second run in the same project directory.  
**Root cause:** HFSS stores the adaptive pass counter in the `.aedtresults/` directory.
If a prior run left this directory:
1. HFSS reads the existing pass counter and thinks the mesh is already converged.
2. It skips the adaptive solve entirely and returns stale S-parameters.
3. OR: the setup registration index is out of sync and fails outright.  
**Fix:** Delete `.aedt`, `.aedt.auto`, `.lock`, and `.aedtresults/` before each run.  
**Code:** [ams/hfss/runner.py](../ams/hfss/runner.py) — `cleanup_hfss_project()`  
**Reference:** `D:/Projects/origami_emi_workflow/guide/03_HFSS_AEDT_CODING_GUIDE.md §3`

---

## BUG-05 — HFSS `_Unnamed_6` non-manifold cleanup object blocks meshing

**Status:** Fixed (post-import cleanup in `make_hfss_em_stage`)  
**Symptom:** HFSS mesh generation fails with `non-manifold geometry` or the adaptive
mesh simply does not converge (refinement keeps looping with no Delta-S improvement).  
**Root cause:** When calling `hfss.modeler.import_3d_cad(path, import_free_surfaces=True)`,
HFSS creates a helper solid named `<stem>_Unnamed_6` to hold the non-manifold edges
from the thin-sheet import.  This object intersects the main geometry and causes the
HFSS mesher to fail.  
**Fix:**
```python
for name in list(hfss.modeler.objects.keys()):
    if name.endswith("_Unnamed_6"):
        hfss.modeler.delete(name)
```
**Code:** [ams/multiphysics/pipeline.py](../ams/multiphysics/pipeline.py) — `run_em()` stage  
**Reference:** `D:/Projects/origami_emi_workflow/guide/03_HFSS_AEDT_CODING_GUIDE.md §4`

---

## BUG-06 — SHELL281 incorrect results for large rotation (origami)

**Status:** Documented — use SHELL181 instead  
**Symptom:** For origami fold angles > ~20° per load step, SHELL281 gives displacement
results that deviate > 10% from SHELL181.  The SHELL281 result appears to be "stiffer"
(underestimates deformation).  
**Root cause:** SHELL281 (8-node midside) uses a higher-order kinematic description that
breaks down under large rotation.  The element does not use the co-rotational frame
used by SHELL181.  
**Fix:** Use SHELL181 for any problem with large rotations (origami, sheet forming,
thin-walled buckling).  SHELL281 is appropriate only for small-rotation, high-accuracy
static problems.  
**Code:** [ams/geometry/element_selector.py](../ams/geometry/element_selector.py) — SHELL181 vs SHELL281 entries  

---

## BUG-07 — `buffer_rgba()` vs `tostring_rgb()` in matplotlib 3.8+

**Status:** Fixed in `postproc.py`  
**Symptom:**
```
AttributeError: FigureCanvasAgg object has no attribute 'tostring_rgb'
```
**Root cause:** matplotlib 3.8 removed `FigureCanvasAgg.tostring_rgb()`.  
**Fix:**
```python
# WRONG (matplotlib < 3.8):
frame = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8).reshape(h, w, 3)

# CORRECT (matplotlib 3.8+):
rgba = np.asarray(fig.canvas.buffer_rgba())   # H×W×4 uint8
frame = rgba[:, :, :3]                        # drop alpha channel
```
**Code:** [ams/mapdl/postproc.py](../ams/mapdl/postproc.py) — `save_animation()`  
**Reference:** `D:/Projects/MAPDL/mapdl_toolbox/postproc.py` (same fix applied there)

---

## BUG-08 — Periodic BC node count mismatch

**Status:** Validated with raise  
**Symptom:** `ValueError: Periodic BC mismatch: 12 nodes on lo-face vs 15 on hi-face`  
**Root cause:** The mesh on the two periodic faces has different node densities.  The
`apply_periodic()` function pairs lo-face nodes with hi-face nodes by their transverse
coordinates; if the counts differ, pairing is impossible.  
**Fix:** Use `MSHKEY,1` (mapped meshing) with `LESIZE` to enforce identical node counts
on opposite faces.  In nTopology, use the "periodic" meshing option if available.  
**Code:** [ams/mapdl/boundary.py](../ams/mapdl/boundary.py) — `apply_periodic()` (raises ValueError)

---

## BUG-09 — AUTOTS + ARCLEN conflict

**Status:** Documented — disable AUTOTS when using ARCLEN  
**Symptom:** Arc-length method does not activate; MAPDL reverts to standard NR.  
**Root cause:** AUTOTS manages the load step size independently.  When both AUTOTS and
ARCLEN are active, they conflict and ARCLEN is silently suppressed.  
**Fix:** Set `solver.autots: false` whenever `solver.arclen: true`.  
**Code:** [ams/mapdl/solver.py](../ams/mapdl/solver.py) — `_solve_static()` (documented)

---

## BUG-10 — RST file fills disk on long parametric sweeps

**Status:** Documented — use `OUTRES,LAST` for production  
**Symptom:** Disk full during a sweep.  RST file for a 200-substep run with 50k elements
can exceed 10 GB.  
**Root cause:** `mapdl.outres('ALL', 'ALL')` writes every substep, every node, every
element quantity.  For parametric sweeps this accumulates rapidly.  
**Fix:** For production sweeps, use `OUTRES,LAST,ALL` (stores only the final result).
For debugging convergence, use `OUTRES,ALL,ALL` on a single run.  
**Code:** [ams/mapdl/solver.py](../ams/mapdl/solver.py) — `_solve_static()` (uses ALL for now; change for sweeps)

---

## BUG-11 — Windows console encoding error on Unicode output

**Status:** Fixed in all print statements  
**Symptom:**
```
UnicodeEncodeError: 'charmap' codec can't encode character '→' in position 22
```
**Root cause:** Windows cmd/PowerShell uses `cp1252` encoding by default.  Arrow
characters (`→`), em-dashes (`—`), and emoji (`✓`, `⚠`, `✗`) cannot be encoded.  
**Fix:** Replace all Unicode symbols in print/log output with ASCII equivalents.
Run Python with `-X utf8` flag if Unicode output is required:
```cmd
python -X utf8 smoke_tests/run_all.py
```
**Code:** All print statements in `ams/` use ASCII-safe characters.
