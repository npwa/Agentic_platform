#!/usr/bin/env python3
"""Build a part -> material -> simulation-run knowledge graph from a HotSpot
example (floorplan, materials, config, power trace) using networkx.

Usage:
    python scripts/ingest_graph.py
    python scripts/ingest_graph.py --example-dir data/hotspot_example1
"""

import argparse
import re
from pathlib import Path

import networkx as nx

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def build_graph(example_dir: Path) -> nx.DiGraph:
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

    graph = nx.DiGraph()
    graph.add_node(floorplan_id, kind="floorplan", source_file=flp_path.name, n_units=len(units))
    graph.add_node(run_id, kind="simulation_run", config_file=config_path.name, package_config_file="package.config")
    graph.add_node(ptrace_id, kind="power_trace", n_samples=n_samples, n_units=len(ptrace_units))

    for material in materials:
        attrs = {k: v for k, v in material.items() if k != "name"}
        graph.add_node(material["name"], kind="material", **attrs)

    graph.add_edge(floorplan_id, run_id, relation="used_in")
    graph.add_edge(ptrace_id, run_id, relation="input_to")
    graph.add_edge(chip_material, run_id, relation="used_in")
    graph.add_edge(sink_material, run_id, relation="used_in")

    for unit in units:
        part_id = f"{floorplan_id}::{unit['name']}"
        attrs = {k: v for k, v in unit.items() if k != "name"}
        attrs["area"] = unit["width"] * unit["height"]
        graph.add_node(part_id, kind="part", label=unit["name"], **attrs)
        graph.add_edge(part_id, floorplan_id, relation="part_of")
        graph.add_edge(part_id, chip_material, relation="made_of")

    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example-dir", type=Path, default=REPO_ROOT / "data" / "hotspot_example1")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "graph")
    parser.add_argument("--out-name", default="knowledge_graph.graphml")
    args = parser.parse_args()

    graph = build_graph(args.example_dir)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / args.out_name
    nx.write_graphml(graph, out_path)

    n_parts = sum(1 for _, attrs in graph.nodes(data=True) if attrs.get("kind") == "part")
    n_materials = sum(1 for _, attrs in graph.nodes(data=True) if attrs.get("kind") == "material")
    print(f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    print(f"  parts={n_parts} materials={n_materials}")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
