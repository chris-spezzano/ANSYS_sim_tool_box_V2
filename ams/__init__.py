"""
ANSYS Simulation Toolbox (ams) — top-level package.

Covers MAPDL (structural / thermal / nonlinear) and HFSS/AEDT
(electromagnetic) workflows with shared resource management,
geometry import, mesh quality, boundary conditions, solver strategy,
live diagnostics, results post-processing, and multi-physics chaining.
"""

__version__ = "1.0.0"
__author__  = "Christopher Spezzano — UC Berkeley"

from .resources.manager  import ResourceManager, kill_ansys_zombies
from .geometry.importer  import GeometryImporter
from .geometry.mesh_quality import MeshQualityChecker
from .mapdl.runner       import MAPDLRunner
from .mapdl.boundary     import apply_boundary_conditions
from .mapdl.solver       import run_solution, SolverStrategy
from .mapdl.postproc     import extract_results, save_plots, save_animation
from .hfss.runner        import HFSSRunner
from .diagnostics.dashboard import LiveDashboard
from .multiphysics.pipeline import (
    SimulationPipeline,
    build_waterbomb_pipeline,
    make_ntop_geometry_stage,
)

__all__ = [
    "ResourceManager",
    "kill_ansys_zombies",
    "GeometryImporter",
    "MeshQualityChecker",
    "MAPDLRunner",
    "apply_boundary_conditions",
    "run_solution",
    "SolverStrategy",
    "extract_results",
    "save_plots",
    "save_animation",
    "HFSSRunner",
    "LiveDashboard",
    "SimulationPipeline",
    "build_waterbomb_pipeline",
    "make_ntop_geometry_stage",
]
