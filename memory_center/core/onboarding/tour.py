"""Architecture tour generator — produce guided walkthroughs for onboarding.

Generates step-by-step architecture tours ordered by dependency topology,
so newcomers can understand the project structure progressively.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..storage.unified import UnifiedStore
from ..reasoning.transitive import TransitiveInferenceEngine


@dataclass
class TourStep:
    """A single step in an architecture tour."""
    step_id: int
    title: str
    description: str
    node_ids: List[str] = field(default_factory=list)
    node_type: str = ""
    depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "description": self.description,
            "node_ids": self.node_ids,
            "node_type": self.node_type,
            "depth": self.depth,
        }


@dataclass
class ArchitectureTour:
    """A complete architecture tour for a workspace."""
    tour_id: str
    persona: str  # developer | architect | product | tester
    scope: str
    steps: List[TourStep] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
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

    def __init__(self, store: UnifiedStore):
        self._store = store

    def generate_tour(
        self,
        persona: str = "developer",
        scope: str = "workspace",
        target: str | None = None,
    ) -> ArchitectureTour:
        """Generate an architecture tour based on persona and scope."""
        steps: List[TourStep] = []
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

    def _get_services(self) -> List[Dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "Service"]

    def _get_endpoints(self) -> List[Dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "Endpoint"]

    def _get_service_classes(self) -> List[Dict[str, Any]]:
        return [
            n for n in self._store.all_nodes()
            if n.get("type") == "Class" and "Service" in n.get("name", "")
        ]

    def _get_feign_clients(self) -> List[Dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "FeignClient"]

    def _get_mq_nodes(self) -> List[Dict[str, Any]]:
        return [
            n for n in self._store.all_nodes()
            if n.get("type") in ("MQConsumer", "MQProducer", "MQTopic")
        ]

    def _get_config_nodes(self) -> List[Dict[str, Any]]:
        return [n for n in self._store.all_nodes() if n.get("type") == "ConfigKey"]
