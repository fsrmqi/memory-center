from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .store import WorkspaceStore


def export_mermaid(workspace_file: str | Path) -> str:
    """Export a coarse service topology diagram in Mermaid format."""
    store = WorkspaceStore(workspace_file)
    topology = store.read_json("service-topology.json", {})
    lines: List[str] = ["flowchart LR"]

    services = topology.get("services", [])
    for svc in services:
        name = _node(svc.get("name") or svc.get("service_name") or "unknown")
        label = svc.get("name") or svc.get("service_name") or "unknown"
        lines.append(f'  {name}["{label}"]')

    for edge in topology.get("feign_edges", []):
        src = _node(edge.get("caller_project") or edge.get("from_project") or "unknown")
        dst = _node(edge.get("target_service") or edge.get("to_service") or edge.get("to_project") or "unknown")
        label = edge.get("client", "Feign")
        lines.append(f'  {src} -- "Feign: {label}" --> {dst}')

    mq_topics = topology.get("mq_topics", {})
    topic_items = mq_topics.items() if isinstance(mq_topics, dict) else [(x.get("topic", "unknown"), x) for x in mq_topics]
    for topic, data in topic_items:
        topic_node = _node(f"topic_{topic}")
        lines.append(f'  {topic_node}(["Topic: {topic}"])')
        for producer in data.get("producers", []):
            producer_project = producer.get("project") if isinstance(producer, dict) else str(producer)
            lines.append(f'  {_node(producer_project)} -- "produce" --> {topic_node}')
        for consumer in data.get("consumers", []):
            consumer_project = consumer.get("project") if isinstance(consumer, dict) else str(consumer)
            lines.append(f'  {topic_node} -- "consume" --> {_node(consumer_project)}')

    return "\n".join(lines) + "\n"


def topology_summary(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    topology = store.read_json("service-topology.json", {})
    return {
        "service_count": len(topology.get("services", [])),
        "feign_edge_count": len(topology.get("feign_edges", [])),
        "mq_topic_count": len(topology.get("mq_topics", {})),
        "services": topology.get("services", []),
    }


def _node(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)
