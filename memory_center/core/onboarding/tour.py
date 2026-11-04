"""Architecture tour generator — produce guided walkthroughs for onboarding.

Generates step-by-step architecture tours ordered by dependency topology,
so newcomers can understand the project structure progressively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..explanation import explanation_entry
from ..storage.runtime import RuntimeStore


@dataclass
class TourStep:
    """A single step in an architecture tour."""
    step_id: int
    title: str
    description: str
    node_ids: list[str] = field(default_factory=list)
    node_type: str = ""
    depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "node_ids": self.node_ids,
            "node_type": self.node_type,
            "depth": self.depth,
        }
        d["_explanation"] = explanation_entry(
            subject=f"tour:step:{self.step_id}",
            summary=self.description,
            evidence=[{"node_type": self.node_type, "node_ids": self.node_ids[:10], "depth": self.depth}],
            semantic_strength="derived",
            confidence=0.8,
            next_refs=[{"id": nid, "name": ""} for nid in self.node_ids[:10]],
        )
        return d


@dataclass
class ArchitectureTour:
    """A complete architecture tour for a workspace."""
    tour_id: str
    persona: str  # developer | architect | product | tester
    scope: str
    steps: list[TourStep] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tour_id": self.tour_id,
            "persona": self.persona,
            "scope": self.scope,
            "steps": [s.to_dict() for s in self.steps],
            "summary": self.summary,
            "total_steps": len(self.steps),
        }


class ArchitectureTourGenerator:
    """Generate guided architecture tours from the code knowledge graph."""

    def __init__(self, store: RuntimeStore):
        self._store = store

    def generate_tour(
        self,
        persona: str = "developer",
        scope: str = "workspace",
        target: str | None = None,
    ) -> ArchitectureTour:
        """Generate an architecture tour based on persona and scope."""
        steps: list[TourStep] = []
        step_id = 0

        # Step 1: Service overview
        services = self._get_services()
        if services:
            step_id += 1
            steps.append(TourStep(
                step_id=step_id,
                title="项目服务概览",
                description=f"本工作区包含 {len(services)} 个服务: {', '.join(s['name'] for s in services[:5])}",
                node_ids=[s.get("id", "") for s in services],
                node_type="Service",
                depth=0,
            ))

        # Step 2: Entry points (endpoints/controllers)
        endpoints = self._get_endpoints()
        if endpoints:
            step_id += 1
            steps.append(TourStep(
                step_id=step_id,
                title="API 入口点",
                description=f"系统暴露了 {len(endpoints)} 个 HTTP 端点",
                node_ids=[e.get("id", "") for e in endpoints[:10]],
                node_type="Endpoint",
                depth=1,
            ))

        # Step 3: Core service layer
        service_classes = self._get_service_classes()
        if service_classes:
            step_id += 1
            steps.append(TourStep(
                step_id=step_id,
                title="核心业务逻辑",
                description=f"核心 Service 类共 {len(service_classes)} 个",
                node_ids=[c.get("id", "") for c in service_classes[:10]],
                node_type="Class",
                depth=2,
            ))

        # Step 4: Feign clients (inter-service calls)
        if persona in ("developer", "architect"):
            feign_clients = self._get_feign_clients()
            if feign_clients:
                step_id += 1
                steps.append(TourStep(
                    step_id=step_id,
                    title="服务间调用 (Feign)",
                    description=f"通过 {len(feign_clients)} 个 Feign 客户端进行跨服务调用",
                    node_ids=[f.get("id", "") for f in feign_clients],
                    node_type="FeignClient",
                    depth=2,
                ))

        # Step 5: MQ consumers/producers
        mq_nodes = self._get_mq_nodes()
        if mq_nodes:
            step_id += 1
            steps.append(TourStep(
                step_id=step_id,
                title="消息队列 (MQ)",
                description=f"系统通过 {len(mq_nodes)} 个 MQ 节点进行异步通信",
                node_ids=[m.get("id", "") for m in mq_nodes],
                node_type="MQConsumer",
                depth=2,
            ))

        # Step 6: Configuration
        if persona in ("developer", "architect"):
            configs = self._get_config_nodes()
            if configs:
                step_id += 1
                steps.append(TourStep(
                    step_id=step_id,
                    title="配置项",
                    description=f"关键配置项共 {len(configs)} 个",
                    node_ids=[c.get("id", "") for c in configs[:10]],
                    node_type="ConfigKey",
                    depth=3,
                ))

        summary = f"架构导览: {len(steps)} 个步骤, 面向 {persona}"
        if target:
            summary += f", 聚焦 {target}"

        return ArchitectureTour(
            tour_id=f"tour:{scope}:{persona}",
            persona=persona,
            scope=scope,
            steps=steps,
            summary=summary,
        )

    def _get_services(self) -> list[dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "Service"]

    def _get_endpoints(self) -> list[dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "Endpoint"]

    def _get_service_classes(self) -> list[dict[str, Any]]:
        return [
            n for n in self._store.all_nodes()
            if n.get("type") == "Class" and "Service" in n.get("name", "")
        ]

    def _get_feign_clients(self) -> list[dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "FeignClient"]

    def _get_mq_nodes(self) -> list[dict[str, Any]]:
        return [
            n for n in self._store.all_nodes()
            if n.get("type") in ("MQConsumer", "MQProducer", "MQTopic")
        ]

    def _get_config_nodes(self) -> list[dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "ConfigKey"]


def generate_architecture_tour(workspace_file: str | Path, persona: str = "developer") -> dict[str, Any]:
    """Generate an architecture tour for onboarding new developers.

    Walks through the graph to build a guided tour:
    1. Top-level services overview
    2. Key entry points and APIs
    3. Core dependencies and Feign connections
    4. MQ topics and data flows
    5. Configuration patterns
    """
    from memory_center.core.storage.runtime import RuntimeStore
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(workspace_file)
    config = store._config if hasattr(store, '_config') else None
    workspace_name = getattr(config, 'workspace', 'unknown') if config else 'unknown'

    tour_stops: list[dict[str, Any]] = []

    # Stop 1: Workspace overview
    services = [s.name for s in (config.services if config else [])]
    tour_stops.append({
        "stop": 1,
        "title": "工作区概览 / Workspace Overview",
        "description": f"工作区 {workspace_name} 包含 {len(services)} 个服务",
        "content": {"services": services, "workspace": workspace_name},
        "persona_adapted": {
            "developer": "这是你将要工作的项目。了解服务列表是第一步。",
            "architect": "关注服务间的边界划分和依赖方向。",
        }.get(persona, ""),
    })

    # Stop 2: Graph overview
    with RuntimeStore(store.graph_db_path) as graph:
        counts = graph.counts()
        tour_stops.append({
            "stop": 2,
            "title": "图谱概览 / Knowledge Graph",
            "description": f"已索引 {counts.get('nodes', 0)} 个节点、{counts.get('edges', 0)} 条边",
            "content": counts,
        })

    # Stop 3: Key patterns
    tour_stops.append({
        "stop": 3,
        "title": "核心查询模式 / Key Query Patterns",
        "description": "了解常用的查询方式",
        "content": {
            "patterns": [
                {"tool": "mc_lookup", "usage": "查找代码实体、Feign 客户端、API 端点"},
                {"tool": "mc_analyze", "usage": "变更影响分析"},
                {"tool": "group_chain", "usage": "跨项目调用链追踪"},
                {"tool": "mc_resume", "usage": "任务恢复"},
            ],
        },
    })

    return {
        "workspace": workspace_name,
        "persona": persona,
        "total_stops": len(tour_stops),
        "stops": tour_stops,
    }
