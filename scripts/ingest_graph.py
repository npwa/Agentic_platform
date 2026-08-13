#!/usr/bin/env python3
"""Build a part -> material -> simulation-run knowledge graph from a HotSpot
example (floorplan, materials, config, power trace) and persist it to
Neo4j Aura.

Usage:
    python scripts/ingest_graph.py
    python scripts/ingest_graph.py --example-dir data/hotspot_example1
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.graph_db import run_query  # noqa: E402


def parse_floorplan(path: Path) -> list[dict]:
    units = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        name, width, height, left_x, bottom_y = fields[:5]
        units.append(
            {
                "name": name,
                "width": float(width),
                "height": float(height),
                "left_x": float(left_x),
                "bottom_y": float(bottom_y),
            }
        )
    return units


def parse_materials(path: Path) -> list[dict]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.strip().startswith("#")]
    materials = []
    i = 0
    while i < len(lines):
        name, mtype, k, cap = lines[i : i + 4]
        i += 4
        material = {
            "name": name,
            "material_type": mtype,
            "thermal_conductivity": float(k),
            "volumetric_heat_capacity": float(cap),
        }
        if mtype == "fluid":
            material["dynamic_viscosity"] = float(lines[i])
            i += 1
        materials.append(material)
    return materials


def parse_config_directive(path: Path, key: str) -> str | None:
    """Return the value of an *uncommented* '-key value' directive, if present."""
    pattern = re.compile(rf"^\s*-{re.escape(key)}\s+(\S+)")
    for line in path.read_text().splitlines():
        if line.strip().startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def parse_config_float(path: Path, key: str) -> float | None:
    value = parse_config_directive(path, key)
    return float(value) if value is not None else None


def parse_ptrace(path: Path) -> tuple[list[str], int]:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    units = lines[0].split()
    n_samples = len(lines) - 1
    return units, n_samples


def infer_material(name: str, value_key_thermal: str, value_key_cap: str, config_path: Path, materials: list[dict], directive: str, fallback_exclude: set[str]) -> str:
    """Infer which material a config section (chip/sink) uses: prefer an
    explicit uncommented directive, else match k/p values against the
    materials table, else fall back to the first solid material not
    already claimed."""
    explicit = parse_config_directive(config_path, directive)
    if explicit:
        return explicit

    k = parse_config_float(config_path, value_key_thermal)
    cap = parse_config_float(config_path, value_key_cap)
    if k is not None and cap is not None:
        for material in materials:
            if material["material_type"] != "solid":
                continue
            if abs(material["thermal_conductivity"] - k) < 1e-6 and abs(material["volumetric_heat_capacity"] - cap) < 1e-6:
                return material["name"]

    for material in materials:
        if material["material_type"] == "solid" and material["name"] not in fallback_exclude:
            return material["name"]
    return name


def build_graph(example_dir: Path) -> dict:
    flp_path = next(example_dir.glob("*.flp"))
    materials_path = next(example_dir.glob("*.materials"))
    config_path = example_dir / "example.config"
    ptrace_path = next(example_dir.glob("*.ptrace"))

    units = parse_floorplan(flp_path)
    materials = parse_materials(materials_path)
    ptrace_units, n_samples = parse_ptrace(ptrace_path)

    chip_material = infer_material(
        "silicon", "k_chip", "p_chip", config_path, materials, "material_chip", fallback_exclude=set()
    )
    sink_material = infer_material(
        "aluminum", "k_sink", "p_sink", config_path, materials, "material_sink", fallback_exclude={chip_material}
    )

    floorplan_id = flp_path.stem
    run_id = f"{floorplan_id}_run"
    ptrace_id = ptrace_path.name

    # Nodes as (label, id, properties); edges as (from_label, from_id, rel_type, to_label, to_id).
    nodes = [
        ("Floorplan", floorplan_id, {"kind": "floorplan", "source_file": flp_path.name, "n_units": len(units)}),
        (
            "SimulationRun",
            run_id,
            {"kind": "simulation_run", "config_file": config_path.name, "package_config_file": "package.config"},
        ),
        ("PowerTrace", ptrace_id, {"kind": "power_trace", "n_samples": n_samples, "n_units": len(ptrace_units)}),
    ]
    edges = [
        ("Floorplan", floorplan_id, "USED_IN", "SimulationRun", run_id),
        ("PowerTrace", ptrace_id, "INPUT_TO", "SimulationRun", run_id),
        ("Material", chip_material, "USED_IN", "SimulationRun", run_id),
        ("Material", sink_material, "USED_IN", "SimulationRun", run_id),
    ]

    for material in materials:
        attrs = {k: v for k, v in material.items() if k != "name"}
        nodes.append(("Material", material["name"], {"kind": "material", **attrs}))

    for unit in units:
        part_id = f"{floorplan_id}::{unit['name']}"
        attrs = {k: v for k, v in unit.items() if k != "name"}
        attrs["area"] = unit["width"] * unit["height"]
        nodes.append(("Part", part_id, {"kind": "part", "label": unit["name"], **attrs}))
        edges.append(("Part", part_id, "PART_OF", "Floorplan", floorplan_id))
        edges.append(("Part", part_id, "MADE_OF", "Material", chip_material))

    return {"nodes": nodes, "edges": edges}


def write_to_neo4j(elements: dict) -> None:
    for label, node_id, props in elements["nodes"]:
        run_query(f"MERGE (n:{label} {{id: $id}}) SET n += $props", id=node_id, props=props)
    for from_label, from_id, rel_type, to_label, to_id in elements["edges"]:
        run_query(
            f"""
            MATCH (a:{from_label} {{id: $from_id}})
            MATCH (b:{to_label} {{id: $to_id}})
            MERGE (a)-[:{rel_type}]->(b)
            """,
            from_id=from_id,
            to_id=to_id,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example-dir", type=Path, default=REPO_ROOT / "data" / "hotspot_example1")
    args = parser.parse_args()

    elements = build_graph(args.example_dir)
    write_to_neo4j(elements)

    n_parts = sum(1 for _, _, props in elements["nodes"] if props.get("kind") == "part")
    n_materials = sum(1 for _, _, props in elements["nodes"] if props.get("kind") == "material")
    print(f"Graph: {len(elements['nodes'])} nodes, {len(elements['edges'])} edges")
    print(f"  parts={n_parts} materials={n_materials}")
    print("Written to Neo4j")


if __name__ == "__main__":
    main()
