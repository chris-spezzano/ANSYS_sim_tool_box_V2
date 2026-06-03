# MAPDL & HFSS Solver Quick Reference

## MAPDL Static Solver

| Command | Argument | Effect |
|---------|----------|--------|
| `ANTYPE,STATIC` | — | Static structural analysis |
| `NLGEOM,ON` | — | Enable large-deformation kinematics |
| `NROPT,FULL` | FULL/MODI/INIT/UNSYM | Newton-Raphson variant |
| `NSUBST,n,max,min` | integers | Initial/max/min substeps |
| `AUTOTS,ON` | — | Automatic time stepping (bisection on divergence) |
| `LNSRCH,ON` | — | Line search (scales NR step) |
| `CNVTOL,F,,0.005` | label,refval,tol | Force convergence criterion (0.5%) |
| `CNVTOL,U,,0.005` | — | Displacement convergence criterion |
| `NEQIT,25` | integer | Max NR iterations per substep |
| `STABILIZE,CONST,ENERGY,0.05` | — | Artificial damping (level 2 retry) |
| `ARCLEN,ON` | — | Arc-length method (snap-through) |
| `OUTRES,ALL,ALL` | — | Write every substep (debug; disk-heavy) |
| `OUTRES,LAST,ALL` | — | Write only final result (production) |

## MAPDL POST1 Commands

| Command | Effect |
|---------|--------|
| `POST1` | Enter post-processor |
| `SET,LAST` | Read last result set |
| `SET,LIST` | List all available result sets |
| `SET,nset=N` | Read result set N by sequence number |
| `PLNSOL,U,SUM` | Plot displacement magnitude |
| `PLNSOL,S,EQV` | Plot von Mises stress |
| `ETABLE,SIGX,S,X` | Store SX in element table |

## MAPDL NROPT Comparison

| Variant | Tangent [K_T] update | Convergence rate | Use case |
|---------|---------------------|-----------------|----------|
| FULL | Every NR iteration | Quadratic — 3-6 iters | Strong nonlinearity |
| MODI | Once per substep | Linear — 10-20 iters | Mild nonlinearity |
| INIT | Never (elastic K_0) | Sub-linear — 50+ iters | Fallback when FULL diverges |
| UNSYM | Full unsymmetric | Quadratic | Follower forces, non-assoc. plasticity |

## HFSS Setup Commands (PyAEDT)

| Method | Arguments | Effect |
|--------|-----------|--------|
| `hfss.create_setup("name")` | — | Create DrivenModal setup |
| `setup.props["Frequency"]` | `"10GHz"` | Solution frequency |
| `setup.props["MaximumPasses"]` | `6` | Max adaptive mesh refinement passes |
| `setup.props["MaxDeltaS"]` | `0.01` | Convergence: Delta-S < 1% |
| `setup.add_sweep("name")` | — | Add frequency sweep to setup |
| `hfss.analyze()` | — | Run the solve |
| `hfss.validate_full_design()` | — | Check geometry + BCs before solving |

## Convergence Criteria

### MAPDL (structural)
```
Force residual:  ||R|| / ||F_ref|| < epsilon_F  (default 0.5%)
Displacement:    ||delta_u|| / ||u_ref|| < epsilon_U  (default 0.5%)
Both must pass simultaneously.
```

### HFSS (electromagnetic)
```
Delta-S = max|S_ij(pass N) - S_ij(pass N-1)|  < max_delta_s  (default 1%)
Checked after each adaptive mesh refinement pass.
```

## RAM Budget Guide

| Mesh size | Empirical (MB) | Conservative (MB) |
|-----------|---------------|-------------------|
| 1,000 elements | 15 | 25 |
| 10,000 elements | 150 | 250 |
| 50,000 elements | 750 | 1,250 |
| 100,000 elements | 1,500 | 2,500 |
| 500,000 elements | 7,500 | 12,500 |

Rule: `ram_mb = 25 * (n_elements / 1000)` (conservative).  
Set via `mapdl.ram_mb` in config.yaml or `launch_mapdl(ram=ram_mb)`.
