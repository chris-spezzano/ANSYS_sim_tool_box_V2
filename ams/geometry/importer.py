"""
Geometry Importer — load meshes from nTopology (.cdb), STL, STEP, or build
parametric geometries directly in MAPDL.

Supported workflows
-------------------
1. CDB (nTopology export)   — most common; preserves nTop element/node numbering
2. STL (surface mesh)       — used to import deformed shapes from MAPDL into HFSS
3. STEP / IGES / Parasolid  — CAD solid; MAPDL meshes it internally
4. Parametric               — build geometry using MAPDL APDL commands (no file needed)

Critical nTopology CDB notes (from real debugging)
---------------------------------------------------
- nTop exports SOLID185 (3D solid) by default.  For shell/origami models you
  MUST reassign element type after import: mapdl.et(1, 'SHELL181').
- The CDB may include node-coordinate-system rotations (NBLOCK with CS data).
  Call mapdl.nrotat('ALL') to align nodal coordinate systems with the global
  frame before applying displacement BCs, or you will constrain the wrong DOFs.
- Element real constants (section data for shells) are NOT included in the CDB
  exported by older nTop versions — you must assign them manually.
- After import, always call mesh_quality.check() before solving.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def _write_mapdl_cdb(mesh, cdb_path: Path) -> None:
    """Write a MAPDL-compatible CDB from a meshio Mesh object.

    Format is reverse-engineered from MAPDL's own CDWRITE output so that
    CDREAD,DB can read it back without errors.  Key differences from naive
    NBLOCK/EBLOCK writes:
      - ETBLOCK must precede NBLOCK/EBLOCK
      - NBLOCK uses (3i9,6e21.13e3) — 9-wide ints, 21-wide E3 floats
      - EBLOCK uses (19i10) — 10-wide ints; element ID is field 11
      - Triangles encoded as degenerate quads: n4 = n3
    """
    points = mesh.points
    n_nodes = len(points)

    tri_cells = []
    for block in mesh.cells:
        if block.type in ("triangle", "triangle6", "triangle3"):
            tri_cells.append(block.data)
    if not tri_cells:
        for block in mesh.cells:
            tri_cells.append(block.data)

    connectivity = np.vstack(tri_cells)
    n_elems = len(connectivity)

    with open(cdb_path, "w", encoding="ascii") as f:
        f.write("/PREP7\n")

        # ETBLOCK: element type table — must come before EBLOCK.
        # No NUMOFF: that command offsets INCOMING entity IDs and is only
        # needed when merging two databases, not creating a fresh mesh.
        f.write("ETBLOCK,        1,        1\n(2i9,19a9)\n")
        f.write("        1      181" + "        0" * 19 + "\n       -1\n")

        # NBLOCK: node coordinates — format matches MAPDL CDWRITE output
        def _fmt21(v: float) -> str:
            """Format float as exactly 21 chars with 3-digit exponent (e21.13e3)."""
            s = f"{v:.13E}"                  # e.g. "3.0396947860000E+00"
            if "E+" in s:
                m, e = s.split("E+")
                s = m + "E+" + e.zfill(3)   # → "3.0396947860000E+000" (20 chars)
            elif "E-" in s:
                m, e = s.split("E-")
                s = m + "E-" + e.zfill(3)   # → "3.0396947860000E-000" (20 chars)
            return f"{s:>21}"               # right-justify to exactly 21 chars

        f.write(f"NBLOCK,6,SOLID,{n_nodes:10d},{n_nodes:10d}\n")
        f.write("(3i9,6e21.13e3)\n")
        for i, pt in enumerate(points, start=1):
            x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
            f.write(f"{i:9d}{0:9d}{0:9d}{_fmt21(x)}{_fmt21(y)}{_fmt21(z)}\n")
        f.write("N,UNBL,LOC,       -1,\n")

        # EBLOCK: element connectivity
        # Fields (10-wide each): mat type real sec esys 0 0 0 npe 0 elem_id n1 n2 n3 n4
        f.write(f"EBLOCK,19,SOLID,{n_elems:10d},{n_elems:10d}\n")
        f.write("(19i10)\n")
        for i, conn in enumerate(connectivity, start=1):
            n1 = int(conn[0]) + 1
            n2 = int(conn[1]) + 1
            n3 = int(conn[2]) + 1
            row = [1, 1, 1, 1, 0, 0, 0, 0, 4, 0, i, n1, n2, n3, n3]
            f.write("".join(f"{v:10d}" for v in row) + "\n")
        f.write("        -1\n")

        f.write("/GO\nFINISH\n")


class GeometryImporter:
    """Import or build geometry in a live MAPDL session.

    Parameters
    ----------
    mapdl : PyMAPDL instance
        An active MAPDL connection (must be in /PREP7 phase).

    Example
    -------
    >>> from ams import MAPDLRunner
    >>> runner = MAPDLRunner(cfg)
    >>> mapdl  = runner.connect()
    >>> gi = GeometryImporter(mapdl)
    >>> gi.from_cdb("results/geometry/origami_mesh.cdb")
    >>> gi.reassign_element_type("SHELL181", section_thickness_m=0.001)
    """

    def __init__(self, mapdl):
        self._m = mapdl

    # ── CDB import ────────────────────────────────────────────────────────────

    def from_cdb(
        self,
        cdb_path: str | Path,
        reassign_et: str | None = None,
        nrotat_all: bool = True,
    ) -> None:
        """Import a .cdb mesh archive into the current MAPDL session.

        Parameters
        ----------
        cdb_path : str | Path
            Absolute or relative path to the .cdb file.
        reassign_et : str | None
            If set (e.g., 'SHELL181'), reassign ALL elements to this type
            after import.  Essential when nTop exports SOLID185 but you
            need thin-shell behaviour.
        nrotat_all : bool
            Call NROTAT,ALL after import to align nodal coordinate systems
            with the global Cartesian frame.  Required before applying
            Cartesian displacement constraints.  Default True.

        Raises
        ------
        FileNotFoundError
            If cdb_path does not exist.
        RuntimeError
            If MAPDL reports an error during CDREAD.
        """
        cdb_path = Path(cdb_path).resolve()
        if not cdb_path.exists():
            raise FileNotFoundError(f"CDB file not found: {cdb_path}")

        log.info("Importing CDB: %s", cdb_path)
        self._m.prep7()

        # Upload then read via /INPUT (runs NBLOCK/EBLOCK as APDL commands).
        self._m.upload(str(cdb_path))
        self._m.input(cdb_path.name)
        # Re-enter PREP7: our CDB ends with FINISH which drops back to BEGIN level.
        self._m.prep7()

        if nrotat_all:
            # Align all nodal coordinate systems with the global frame so that
            # D,ALL,UX applies correctly regardless of any nTop rotations.
            self._m.nrotat("ALL")
            log.debug("NROTAT,ALL applied — nodal CS aligned with global CS")

        if reassign_et:
            self.reassign_element_type(reassign_et)

        n_nodes = self._m.mesh.n_node
        n_elems = self._m.mesh.n_elem
        log.info("CDB import complete: %d nodes, %d elements", n_nodes, n_elems)
        print(f"Imported: {n_nodes:,} nodes, {n_elems:,} elements from {cdb_path.name}")

    # ── Abaqus .inp import (nTopology Export FE Mesh output) ─────────────────

    def from_inp(
        self,
        inp_path: str | Path,
        reassign_et: str | None = None,
        nrotat_all: bool = True,
    ) -> None:
        """Import an Abaqus .inp mesh exported by nTopology's Export FE Mesh block.

        nTopology 5.x does not support .cdb export directly — use .inp instead.
        This method reads the .inp via meshio and writes a MAPDL-compatible CDB
        (NBLOCK/EBLOCK format) so the rest of the pipeline is unchanged.

        Parameters
        ----------
        inp_path : str | Path
            Absolute or relative path to the .inp file written by nTopology.
        reassign_et : str | None
            Element type to reassign after import (e.g., 'SHELL181').
            nTopology's FE Shell Mesh block writes triangle elements; pass
            'SHELL181' to ensure MAPDL uses the correct formulation.
        nrotat_all : bool
            Align nodal coordinate systems after import (recommended).

        Requires: meshio >= 5.3  (pip install meshio)
        """
        try:
            import meshio
        except ImportError:
            raise ImportError(
                "meshio is required for .inp import.  "
                "Run: pip install meshio>=5.3"
            ) from None

        inp_path = Path(inp_path).resolve()
        if not inp_path.exists():
            raise FileNotFoundError(f"Abaqus .inp file not found: {inp_path}")

        cdb_path = inp_path.with_suffix(".cdb")
        log.info("Converting %s → %s (MAPDL CDB)", inp_path.name, cdb_path.name)
        print(f"Converting {inp_path.name} → {cdb_path.name} ...")

        mesh = meshio.read(str(inp_path))
        # nTopology exports coordinates in mm; MAPDL structural analysis uses
        # SI units (m, Pa, kg).  Scale all node coordinates mm → m here so
        # material properties, section thickness, and BCs stay in consistent
        # SI units throughout the pipeline.
        mesh.points = mesh.points * 1e-3
        _write_mapdl_cdb(mesh, cdb_path)

        log.info("CDB written: %d nodes, %d elements (coords scaled mm→m)",
                 len(mesh.points), sum(len(b.data) for b in mesh.cells))

        self.from_cdb(cdb_path, reassign_et=reassign_et, nrotat_all=nrotat_all)

    # ── STL import (for HFSS / geometry reference) ───────────────────────────

    def from_stl_to_mapdl(
        self,
        stl_path: str | Path,
        facet_tol_m: float = 1e-6,
    ) -> None:
        """Import an STL surface mesh and attempt to reconstruct a solid.

        Note: STL import via IGESIN works best for simple, watertight surfaces.
        For complex origami geometries, prefer importing as a CDB.

        Parameters
        ----------
        stl_path : str | Path
            Path to the STL file.
        facet_tol_m : float
            Facet tolerance for surface reconstruction (default: 1 µm).
        """
        stl_path = Path(stl_path).resolve()
        if not stl_path.exists():
            raise FileNotFoundError(f"STL file not found: {stl_path}")

        log.info("Importing STL geometry: %s", stl_path)
        self._m.prep7()
        # MAPDL can read STL via IGESIN with FACETS option
        self._m.run("/AUX15")
        self._m.run(f"IGESIN,'{stl_path.stem}','{stl_path.suffix.strip('.')}','{stl_path.parent}'")
        self._m.run("/PREP7")
        log.info("STL geometry imported")

    # ── STEP / IGES / Parasolid import ────────────────────────────────────────

    def from_cad(
        self,
        cad_path: str | Path,
        format: str = "STEP",
    ) -> None:
        """Import a CAD solid model (STEP, IGES, Parasolid).

        After import, you must:
        1. Run mesh_quality.check() to verify the solid is watertight.
        2. Set element type and material via MAPDL commands.
        3. Call amesh() or vmesh() to generate the FE mesh.

        Parameters
        ----------
        cad_path : str | Path
            Path to the CAD file.
        format : str
            'STEP' | 'IGES' | 'X_T' (Parasolid).
        """
        cad_path = Path(cad_path).resolve()
        if not cad_path.exists():
            raise FileNotFoundError(f"CAD file not found: {cad_path}")

        fmt = format.upper()
        self._m.prep7()

        if fmt in ("STEP", "STP"):
            self._m.run(f"~SATIN,'{cad_path.stem}',STEP,'{cad_path.parent}',SOLIDS,0")
        elif fmt in ("IGES", "IGS"):
            self._m.run(f"~PARAIN,'{cad_path.stem}',IGS,'{cad_path.parent}'")
        elif fmt in ("X_T", "XT", "PARASOLID"):
            self._m.run(f"~PARAIN,'{cad_path.stem}',X_T,'{cad_path.parent}'")
        else:
            raise ValueError(f"Unsupported CAD format: {format!r}. Use STEP, IGES, or X_T.")

        log.info("CAD import complete (%s): %s", fmt, cad_path.name)

    # ── Parametric geometry ───────────────────────────────────────────────────

    def build_plate_with_hole(
        self,
        width_m:  float = 0.10,
        height_m: float = 0.10,
        depth_m:  float = 0.005,
        hole_r_m: float = 0.010,
    ) -> None:
        """Build a plate-with-hole solid geometry in MAPDL PREP7.

        This is a benchmark geometry with a known analytical stress concentration
        factor Kt = 3.0 (Kirsch solution, circular hole in infinite plate under
        uniaxial tension).  Useful for validating solver and mesh quality.

        Mathematical background
        -----------------------
        Kirsch (1898) solution for σ_θθ on the hole boundary (θ=90°):
            σ_θθ = σ_far × (1 + 2) = 3 σ_far
        where σ_far is the far-field applied stress (Kt = 3 for an infinite plate).
        For a finite plate (hole_r / half_width = 0.1):
            Kt ≈ 3.04 (Pilkey, 2008, §4.3.2)

        Parameters
        ----------
        width_m, height_m, depth_m : float
            Plate dimensions in meters.
        hole_r_m : float
            Hole radius in meters.  Must be < min(width_m, height_m) / 2.
        """
        if hole_r_m >= min(width_m, height_m) / 2:
            raise ValueError("hole_r_m must be less than half the smallest plate dimension")

        m = self._m
        m.prep7()

        # Solid plate block
        m.block(0, width_m, 0, height_m, 0, depth_m)

        # Cylindrical hole through depth
        m.cyl4(width_m / 2, height_m / 2, hole_r_m, "", "", "", depth_m)

        # Boolean: subtract hole from plate
        m.vsbv(1, 2)

        log.info(
            "Plate-with-hole created: %.3f × %.3f × %.3f m, hole_r=%.4f m",
            width_m, height_m, depth_m, hole_r_m,
        )

    def build_beam(
        self,
        length_m: float = 1.0,
        cross_section: str = "RECT",
        w_m: float = 0.05,
        h_m: float = 0.10,
    ) -> None:
        """Build a simple beam for benchmarking beam/shell element behaviour.

        Parameters
        ----------
        length_m : float
            Beam length along X.
        cross_section : str
            'RECT' (rectangular) | 'CIRC' (circular).
        w_m, h_m : float
            Width and height for RECT cross-section (w = diameter for CIRC).
        """
        m = self._m
        m.prep7()
        if cross_section.upper() == "RECT":
            m.block(0, length_m, -w_m / 2, w_m / 2, -h_m / 2, h_m / 2)
            log.info("Beam created: %.3f m long, %.3f × %.3f m cross-section", length_m, w_m, h_m)
        elif cross_section.upper() == "CIRC":
            m.cyl4(0, 0, w_m / 2, "", "", "", length_m)
            log.info("Beam created: %.3f m long, circular r=%.4f m", length_m, w_m / 2)
        else:
            raise ValueError(f"Unknown cross_section: {cross_section!r}")

    # ── Element type reassignment ─────────────────────────────────────────────

    def reassign_element_type(
        self,
        element_type: str,
        et_id: int = 1,
        section_thickness_m: float | None = None,
        keyopt_overrides: dict[int, int] | None = None,
    ) -> None:
        """Reassign all elements to a new element type.

        This is necessary when a CDB exported by nTopology contains SOLID185
        elements but the physics requires thin-shell behaviour (SHELL181).

        Parameters
        ----------
        element_type : str
            MAPDL element type string, e.g., 'SHELL181', 'PLANE182', 'SOLID186'.
        et_id : int
            Element type ID number (1-based; default 1).
        section_thickness_m : float | None
            Shell thickness in meters.  Required when element_type is SHELL*.
        keyopt_overrides : dict[int, int] | None
            KEYOPT(n) = value overrides, e.g., {3: 2} sets KEYOPT(3)=2.
        """
        m = self._m
        m.prep7()
        m.et(et_id, element_type)

        if keyopt_overrides:
            for k, v in keyopt_overrides.items():
                # Accept "k1" / "k3" style keys from YAML as well as plain ints
                knum = int(str(k).lstrip("k") or 0)
                if knum > 0:
                    m.keyopt(et_id, knum, v)

        if element_type.upper().startswith("SHELL") and section_thickness_m is not None:
            m.sectype(et_id, "SHELL")
            m.secdata(section_thickness_m)
            log.info("Shell section defined: thickness = %.6f m", section_thickness_m)

        # Reassign all existing elements to new type
        m.emodif("ALL", "TYPE", et_id)

        log.info("All elements reassigned to %s (ET %d)", element_type, et_id)
        print(f"Element type set to {element_type} (ID {et_id})")

    # ── Geometry export ───────────────────────────────────────────────────────

    def export_stl(
        self,
        output_path: str | Path,
        deform_scale: float = 1.0,
    ) -> Path:
        """Export the current deformed geometry as an STL file.

        Used to pass the deformed structural shape to HFSS for EM simulation.

        Parameters
        ----------
        output_path : str | Path
            Absolute path for the output STL file.
        deform_scale : float
            Displacement scale factor (1.0 = actual displacements).

        Returns
        -------
        Path to the written STL file.
        """
        out = Path(output_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        m = self._m
        m.post1()
        m.set("LAST")
        m.run("PLNSOL,U,SUM")
        # Use PyVista to export deformed mesh as STL
        try:
            import numpy as np

            mesh   = m.mesh._surf
            nodes  = m.mesh.nodes
            ux = np.asarray(m.post_processing.nodal_displacement("X"))
            uy = np.asarray(m.post_processing.nodal_displacement("Y"))
            uz = np.asarray(m.post_processing.nodal_displacement("Z"))
            n = len(nodes)
            disp = np.column_stack([ux[:n], uy[:n], uz[:n]]) * deform_scale

            node_ids = (mesh["ansys_node_num"].astype(int) - 1)
            mesh.point_data["displacement"] = disp[node_ids]
            deformed = mesh.warp_by_vector("displacement", factor=1.0)

            deformed.save(str(out))
            log.info("Deformed STL exported → %s", out)
            print(f"STL exported → {out}")
        except Exception as exc:
            log.error("STL export failed: %s", exc)
            raise
        return out
