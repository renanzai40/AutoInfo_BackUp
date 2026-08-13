from __future__ import annotations

"""Knowledge graph CLI — query and export the knowledge graph.

Usage::

    autoinfo knowledge graph export --domain medical-research
    autoinfo knowledge graph export --domain medical-research --format json
    autoinfo knowledge graph export --domain medical-research --format graphml
    autoinfo knowledge graph export --domain medical-research --format csv
"""


import csv
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import typer

knowledge_app = typer.Typer(help="Knowledge graph operations")
graph_app = typer.Typer(help="Knowledge graph operations")

knowledge_app.add_typer(graph_app, name="graph")


# ---------------------------------------------------------------------------
# GraphML XML helpers
# ---------------------------------------------------------------------------


def _build_graphml(data: dict[str, Any]) -> str:
    """Build a GraphML XML string from knowledge graph data."""
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")

    # Node attribute keys
    key_id = ET.SubElement(root, "key")
    key_id.set("id", "k0")
    key_id.set("for", "node")
    key_id.set("attr.name", "entity_type")
    key_id.set("attr.type", "string")

    key_name = ET.SubElement(root, "key")
    key_name.set("id", "k1")
    key_name.set("for", "node")
    key_name.set("attr.name", "entity_name")
    key_name.set("attr.type", "string")

    # Edge attribute keys
    key_rel = ET.SubElement(root, "key")
    key_rel.set("id", "k2")
    key_rel.set("for", "edge")
    key_rel.set("attr.name", "relation_type")
    key_rel.set("attr.type", "string")

    key_str = ET.SubElement(root, "key")
    key_str.set("id", "k3")
    key_str.set("for", "edge")
    key_str.set("attr.name", "strength")
    key_str.set("attr.type", "double")

    graph = ET.SubElement(root, "graph")
    graph.set("id", "G")
    graph.set("edgedefault", "undirected")

    # Collect unique entity IDs referenced in relations
    related_entity_ids: set[str] = set()
    for rel in data.get("relations", []):
        related_entity_ids.add(rel.get("entity_a", ""))
        related_entity_ids.add(rel.get("entity_b", ""))

    # Nodes — only include entities that appear in relations or all if no relations
    entity_map: dict[str, dict[str, Any]] = {}
    for ent in data.get("entities", []):
        eid = ent.get("entity_id", "")
        entity_map[eid] = ent

    if related_entity_ids:
        node_entities = {
            eid: entity_map[eid]
            for eid in related_entity_ids
            if eid in entity_map
        }
    else:
        node_entities = entity_map

    for eid, ent in node_entities.items():
        node = ET.SubElement(graph, "node")
        node.set("id", eid)
        d0 = ET.SubElement(node, "data")
        d0.set("key", "k0")
        d0.text = ent.get("type", "")
        d1 = ET.SubElement(node, "data")
        d1.set("key", "k1")
        d1.text = ent.get("name", eid)

    # Edges
    for i, rel in enumerate(data.get("relations", [])):
        edge = ET.SubElement(graph, "edge")
        edge.set("id", f"e{i}")
        edge.set("source", rel.get("entity_a", ""))
        edge.set("target", rel.get("entity_b", ""))
        d2 = ET.SubElement(edge, "data")
        d2.set("key", "k2")
        d2.text = rel.get("relation_type", "related_to")
        d3 = ET.SubElement(edge, "data")
        d3.set("key", "k3")
        d3.text = str(rel.get("strength", 1.0))

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


# ---------------------------------------------------------------------------
# CSV export helpers
# ---------------------------------------------------------------------------


def _write_csv(data: dict[str, Any], output_stem: str) -> dict[str, str]:
    """Write entities.csv and relations.csv files.

    Returns a dict with ``entities`` and ``relations`` file paths.
    """
    entities_path = Path(f"{output_stem}_entities.csv")
    relations_path = Path(f"{output_stem}_relations.csv")

    # Entities CSV
    with entities_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["entity_id", "name", "type", "domain", "entry_id", "created_at"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for ent in data.get("entities", []):
            writer.writerow(ent)

    # Relations CSV
    with relations_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "relation_id", "entity_a", "entity_a_name",
                "entity_b", "entity_b_name", "relation_type",
                "strength", "entries_shared", "domain", "created_at",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for rel in data.get("relations", []):
            writer.writerow(rel)

    return {
        "entities": str(entities_path),
        "relations": str(relations_path),
    }


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


@graph_app.command()
def export(
    domain: str = typer.Option(
        ..., "--domain", help="Domain to export knowledge graph for"
    ),
    format: str = typer.Option(
        "json",
        "--format",
        help="Export format: json (default), graphml, csv",
    ),
    output: str = typer.Option(
        "",
        "--output",
        help="Output file path (default: knowledge_graph_export.<format>)",
    ),
) -> None:
    """Export the knowledge graph for a domain.

    Produces a file containing all entities and relations from the
    knowledge graph, in the requested format.
    """
    valid_formats = {"json", "graphml", "csv"}
    if format not in valid_formats:
        typer.echo(
            f"Error: Unsupported format '{format}'. "
            f"Supported: {', '.join(sorted(valid_formats))}",
            err=True,
        )
        raise typer.Exit(code=1)

    from autoinfo.kb import KBStore

    store = KBStore()
    data = store.export_knowledge_graph(domain=domain)

    # Resolve output path
    out_path = Path(output) if output else Path(f"knowledge_graph_export.{format}")

    try:
        if format == "json":
            content = json.dumps(data, ensure_ascii=False, indent=2)
            out_path.write_text(content, encoding="utf-8")
            typer.echo(f"Exported knowledge graph to {out_path}")

        elif format == "graphml":
            xml_content = _build_graphml(data)
            out_path.write_text(xml_content, encoding="utf-8")
            typer.echo(f"Exported knowledge graph to {out_path}")

        elif format == "csv":
            stem = str(out_path.with_suffix(""))
            paths = _write_csv(data, stem)
            typer.echo(
                f"Exported knowledge graph:\n"
                f"  Entities: {paths['entities']}\n"
                f"  Relations: {paths['relations']}"
            )

    except OSError as exc:
        typer.echo(f"Error writing export file: {exc}", err=True)
        raise typer.Exit(code=1) from exc
