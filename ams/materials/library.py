"""Central material property library loader (config/materials.yaml)."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml


def load_materials_yaml(path) -> dict:
    """Load config/materials.yaml and return its `materials:` mapping."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("materials", {})


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into a copy of `base` and return it."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_material_config(material_cfg: dict, materials_yaml_path) -> dict:
    """Resolve an experiment config's `material:` block to a flat material dict.

    `material_cfg` is expected to be `{"ref": "<name in materials.yaml>", ...}`,
    where any additional keys are deep-merged on top of the referenced entry as
    per-experiment overrides.

    Returns a flat dict shaped like the legacy inline `material:` block:
    {name, model, E_Pa, nu, density_kg_m3, biso, chaboche, fatigue, thermal,
    electromagnetic, lemaitre_cdm, electrical_damage_coupling,
    thermal_damage_coupling}. The last three are CDM/EMI-demo extensions
    (emi_crease_demo/, emi_physics/); absent for materials that don't define
    them (e.g. aluminum_6061_T6, copper).
    """
    materials_yaml_path = Path(materials_yaml_path)
    materials = load_materials_yaml(materials_yaml_path)

    ref = material_cfg["ref"]
    if ref not in materials:
        raise KeyError(
            f"Material {ref!r} not found in {materials_yaml_path} "
            f"(available: {sorted(materials)})"
        )
    entry = materials[ref]

    mech  = entry.get("mechanical", {})
    plast = entry.get("plasticity", {})

    resolved = {
        "name":            ref,
        "model":           plast.get("model", "elastic"),
        "E_Pa":            mech.get("E_Pa"),
        "nu":              mech.get("nu"),
        "density_kg_m3":   mech.get("density_kg_m3"),
        "biso":            plast.get("biso", {}),
        "chaboche":        plast.get("chaboche", {}),
        "fatigue":         entry.get("fatigue", {}),
        "thermal":         entry.get("thermal", {}),
        "electromagnetic": entry.get("electromagnetic", {}),
        "lemaitre_cdm":                entry.get("lemaitre_cdm", {}),
        "electrical_damage_coupling":  entry.get("electrical_damage_coupling", {}),
        "thermal_damage_coupling":     entry.get("thermal_damage_coupling", {}),
    }

    overrides = {k: v for k, v in material_cfg.items() if k != "ref"}
    if overrides:
        resolved = _deep_merge(resolved, overrides)

    return resolved
