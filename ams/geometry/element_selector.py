"""
Element Selector — guide users to choose the right ANSYS element type.

ANSYS has hundreds of element types.  Choosing wrong leads to:
- Incorrect physics (SOLID185 for thin sheets — shear locking)
- Wasted compute (SOLID186 for simple tension — unnecessary midside nodes)
- Convergence failures (SHELL281 for large rotations > 20°)

This module provides an interactive decision tree and element reference.

Mathematical background
-----------------------
Finite elements approximate the displacement field u(x) as:

    u(x) = Σᵢ Nᵢ(x) · uᵢ

where Nᵢ are shape functions and uᵢ are nodal values.

Element "order" refers to the polynomial degree of Nᵢ:
  - Linear (serendipity):   Nᵢ ∝ 1 + ξ + η          (e.g., PLANE182, SOLID185)
  - Quadratic (midside):    Nᵢ ∝ 1 + ξ + η + ξ² + η² (e.g., PLANE183, SOLID186)

Higher-order elements are more accurate per element but cost more per solve.
For smooth problems: 1 quadratic > ~4 linear (in terms of accuracy per DOF).
For shock / plasticity fronts: linear with dense mesh often wins.

Locking
-------
"Locking" is when element constraints prevent physically correct deformation.

Shear locking (bending-dominated problems):
    Linear elements in bending develop a spurious transverse shear strain
    that stiffens the response.  Fix: use reduced integration (KEYOPT(2)=1)
    or switch to quadratic elements.

Volumetric locking (nearly incompressible materials, ν → 0.5):
    Constant-volume constraint is over-enforced.  Fix:
    - PLANE182/SOLID185 with KEYOPT(6)=1 (B-bar mixed formulation)
    - PLANE183/SOLID186 (quadratic, less susceptible)
    - SOLID285 (pressure-stabilized tet)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ElementInfo:
    """Specification for one ANSYS element type."""
    name:             str
    family:           str         # structural | thermal | em | beam | shell | fluid
    spatial_dim:      int         # 2 or 3
    n_nodes:          int
    integration:      str         # full | reduced | selective
    large_deform:     bool
    best_for:         list[str]
    avoid_for:        list[str]
    keyopt_notes:     dict[int, str] = field(default_factory=dict)
    reference:        str = ""


# ── Element library ───────────────────────────────────────────────────────────

ELEMENT_LIBRARY: dict[str, ElementInfo] = {

    "PLANE182": ElementInfo(
        name         = "PLANE182",
        family       = "structural",
        spatial_dim  = 2,
        n_nodes      = 4,
        integration  = "selective",
        large_deform = True,
        best_for     = [
            "Plane stress / plane strain / axisymmetric problems",
            "Quick mesh convergence studies",
            "Patch tests and validation",
        ],
        avoid_for    = [
            "High-accuracy stress gradients (use PLANE183 instead)",
            "Bending-dominated structures without KEYOPT(1)=1",
        ],
        keyopt_notes = {
            1: "0=uniform reduced integration (1 pt), 1=full (2×2 pts, default)",
            3: "0=plane stress, 1=plane strain, 2=axisymmetric, 3=plane stress + thickness",
            6: "0=standard, 1=mixed u-P formulation (near-incompressible, ν>0.49)",
        },
        reference = "ANSYS Element Reference §14.182",
    ),

    "PLANE183": ElementInfo(
        name         = "PLANE183",
        family       = "structural",
        spatial_dim  = 2,
        n_nodes      = 8,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "2D with curved boundaries (midside nodes capture curvature)",
            "Higher accuracy without mesh refinement",
            "Stress concentration problems",
        ],
        avoid_for    = [
            "Very large meshes (8-node quad = 4× the DOFs of PLANE182)",
        ],
        keyopt_notes = {
            3: "0=plane stress, 1=plane strain, 2=axisymmetric",
        },
        reference = "ANSYS Element Reference §14.183",
    ),

    "SOLID185": ElementInfo(
        name         = "SOLID185",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 8,
        integration  = "selective",
        large_deform = True,
        best_for     = [
            "3D structural solids — most robust general-purpose element",
            "Large deformation / large strain (Lagrangian or ALE)",
            "Plasticity, creep, hyperelasticity",
        ],
        avoid_for    = [
            "Thin shells (shear locking — use SHELL181 instead)",
            "Bending of beams (use BEAM188 instead)",
        ],
        keyopt_notes = {
            2: "0=full integration (default, more robust), 1=reduced (faster, hourglass risk)",
            6: "0=standard, 1=mixed u-P (near-incompressible)",
        },
        reference = "ANSYS Element Reference §14.185",
    ),

    "SOLID186": ElementInfo(
        name         = "SOLID186",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 20,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "High accuracy — quadratic displacement field",
            "Curved surfaces (midside nodes lie on the geometry)",
            "Stress concentration / singularity regions",
            "p-version type analyses",
        ],
        avoid_for    = [
            "Very large meshes (20-node hex is expensive per element)",
            "Meshes imported from nTopology (they export 8-node hex — convert first)",
        ],
        keyopt_notes = {
            2: "0=full integration (3×3×3 = 27 pts), 1=reduced (2×2×2 = 8 pts)",
        },
        reference = "ANSYS Element Reference §14.186",
    ),

    "SOLID187": ElementInfo(
        name         = "SOLID187",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 10,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "Complex 3D geometries (auto-meshable tetrahedral)",
            "Geometries imported from STEP / IGES / STL",
            "When hex meshing is too difficult",
        ],
        avoid_for    = [
            "Nearly incompressible materials (ν > 0.49) — volumetric locking",
            "High accuracy with coarse mesh (tet10 generally needs 5× more elements than hex8)",
        ],
        keyopt_notes = {},
        reference = "ANSYS Element Reference §14.187",
    ),

    "SHELL181": ElementInfo(
        name         = "SHELL181",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 4,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "Thin shells with large rotations (origami, sheet metal forming)",
            "Composite laminates (section layup via SECDATA)",
            "Structural instability / buckling of shells",
        ],
        avoid_for    = [
            "Thick sections (thickness/span > 0.1 — use SOLID elements instead)",
        ],
        keyopt_notes = {
            1: "0=reduced+hourglass control (recommended for large deformation)",
            3: "0=membrane+bending, 1=membrane only, 2=bending only",
        },
        reference = "ANSYS Element Reference §14.181",
    ),

    "SHELL281": ElementInfo(
        name         = "SHELL281",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 8,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "High-accuracy thin shell analysis",
            "Small-rotation problems requiring high stress accuracy",
        ],
        avoid_for    = [
            "Large rotation problems (> 20° per load step) — known locking in large rotation",
            "Origami / sheet metal forming — use SHELL181 instead",
        ],
        keyopt_notes = {
            3: "0=membrane+bending (default), 1=membrane only",
        },
        reference = "ANSYS Element Reference §14.281",
    ),

    "BEAM188": ElementInfo(
        name         = "BEAM188",
        family       = "structural",
        spatial_dim  = 3,
        n_nodes      = 2,
        integration  = "full",
        large_deform = True,
        best_for     = [
            "Slender beams and frames",
            "All section types (SECTYPE: RECT, CIRC, I, T, etc.)",
            "Large deformation / buckling of beams",
        ],
        avoid_for    = [
            "Short beams (length/depth < 10) — deep beam shear effects not captured",
        ],
        keyopt_notes = {
            1: "0=linear, 1=quadratic, 2=cubic interpolation along length",
            3: "0=six DOFs, 1=six DOFs + warping (open sections)",
        },
        reference = "ANSYS Element Reference §14.188",
    ),

    "PLANE223": ElementInfo(
        name         = "PLANE223",
        family       = "coupled",
        spatial_dim  = 2,
        n_nodes      = 8,
        integration  = "full",
        large_deform = False,
        best_for     = [
            "2D coupled-field: piezoelectric, thermoelectric, piezoresistive",
            "EM-thermal-structural coupling",
        ],
        avoid_for    = ["Pure structural problems (use PLANE183)"],
        keyopt_notes = {
            1: "0=plane stress, 1=plane strain",
        },
        reference = "ANSYS Element Reference §14.223",
    ),

    "SOLID226": ElementInfo(
        name         = "SOLID226",
        family       = "coupled",
        spatial_dim  = 3,
        n_nodes      = 20,
        integration  = "full",
        large_deform = False,
        best_for     = [
            "3D coupled-field: piezoelectric, thermoelectric",
            "Multi-physics: structural + thermal + electric",
        ],
        avoid_for    = ["Pure structural problems (costly DOF set)"],
        keyopt_notes = {
            1: "Activate coupled-field DOFs: 0=none, 1=thermal, 100=piezo, etc.",
        },
        reference = "ANSYS Element Reference §14.226",
    ),
}


def choose_element(
    spatial_dim: int = 3,
    physics: str = "structural",
    is_thin_shell: bool = False,
    is_beam: bool = False,
    large_deformation: bool = True,
    nearly_incompressible: bool = False,
    high_accuracy: bool = False,
    auto_meshable: bool = False,
    coupled_field: bool = False,
) -> ElementInfo:
    """Recommend an element type based on problem characteristics.

    Parameters
    ----------
    spatial_dim : int
        2 for plane problems, 3 for full 3D.
    physics : str
        'structural' | 'thermal' | 'coupled'.
    is_thin_shell : bool
        True for thin-walled structures where thickness << span.
    is_beam : bool
        True for slender beam/frame structures.
    large_deformation : bool
        True if displacements > ~5% of characteristic length.
    nearly_incompressible : bool
        True for rubber (ν ≈ 0.499) or biological tissue.
        Requires mixed u-P formulation.
    high_accuracy : bool
        Use quadratic (midside-node) elements for better accuracy per element.
    auto_meshable : bool
        True when using complex CAD geometry requiring tetrahedral meshing.
    coupled_field : bool
        True when multiple physics are coupled (e.g., piezo, thermo-structural).

    Returns
    -------
    ElementInfo
        The recommended element.

    Example
    -------
    >>> elem = choose_element(spatial_dim=3, is_thin_shell=True, large_deformation=True)
    >>> print(elem.name)   # SHELL181
    """
    # Beam
    if is_beam and spatial_dim == 3:
        return ELEMENT_LIBRARY["BEAM188"]

    # Thin shell
    if is_thin_shell:
        if high_accuracy:
            return ELEMENT_LIBRARY["SHELL281"]
        return ELEMENT_LIBRARY["SHELL181"]

    # Coupled-field
    if coupled_field:
        if spatial_dim == 2:
            return ELEMENT_LIBRARY["PLANE223"]
        return ELEMENT_LIBRARY["SOLID226"]

    # 2D problems
    if spatial_dim == 2:
        if high_accuracy:
            return ELEMENT_LIBRARY["PLANE183"]
        return ELEMENT_LIBRARY["PLANE182"]

    # 3D solid
    if auto_meshable:
        return ELEMENT_LIBRARY["SOLID187"]
    if high_accuracy:
        return ELEMENT_LIBRARY["SOLID186"]
    return ELEMENT_LIBRARY["SOLID185"]


def print_element_guide() -> None:
    """Print a reference table of all supported elements."""
    print("\n" + "=" * 80)
    print("  ANSYS Element Quick Reference")
    print("=" * 80)
    print(f"  {'Name':<12} {'Dim':>4} {'Nodes':>6} {'Family':<12}  Best for (abbreviated)")
    print("  " + "-" * 76)
    for name, info in ELEMENT_LIBRARY.items():
        best = info.best_for[0][:46] if info.best_for else ""
        ld = "✓" if info.large_deform else " "
        print(f"  {name:<12} {info.spatial_dim:>4} {info.n_nodes:>6} {info.family:<12}  [{ld}LD] {best}")
    print("=" * 80)
    print("  ✓LD = large deformation capable\n")


def apply_element_to_mapdl(
    mapdl,
    element_name: str,
    et_id: int = 1,
    keyopts: dict[int, int] | None = None,
) -> None:
    """Apply an element type and its recommended KEYOPT settings to MAPDL.

    Parameters
    ----------
    mapdl : PyMAPDL instance
    element_name : str
        Element name, e.g., 'SHELL181'.
    et_id : int
        Element type ID (1-based).
    keyopts : dict[int, int] | None
        Override specific KEYOPT values.  If None, uses recommended defaults.
    """
    info = ELEMENT_LIBRARY.get(element_name.upper())
    mapdl.et(et_id, element_name)

    if keyopts:
        for k, v in keyopts.items():
            mapdl.keyopt(et_id, k, v)

    import logging
    log = logging.getLogger(__name__)
    log.info("Element %s applied as ET %d", element_name, et_id)
    if info:
        for k, note in info.keyopt_notes.items():
            log.debug("  KEYOPT(%d): %s", k, note)
