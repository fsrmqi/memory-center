"""Onboarding guide generator — produce structured onboarding plans.

Generates role-specific onboarding guides with recommended reading order,
key concepts, and first tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..storage.unified import UnifiedStore
from .glossary import GlossaryExtractor
from .tour import ArchitectureTourGenerator


@dataclass
class GuideSection:
    """A section of the onboarding guide."""
    section_id: int
    title: str
    content: str
    action_items: List[str] = field(default_factory=list)
    related_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "content": self.content,
            "action_items": self.action_items,
            "related_nodes": self.related_nodes[:10],
        }


@dataclass
class OnboardingGuide:
    """Complete onboarding guide for a workspace."""
    guide_id: str
    persona: str
    sections: List[GuideSection] = field(default_factory=list)
    glossary_terms: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guide_id": self.guide_id,
            "persona": self.persona,
            "sections": [s.to_dict() for s in self.sections],
            "glossary_terms": self.glossary_terms[:20],
            "total_sections": len(self.sections),
        }


class OnboardingGuideGenerator:
    """Generate structured onboarding guides from the code knowledge graph."""

    def __init__(self, store: UnifiedStore):
        self._store = store
        self._tour_gen = ArchitectureTourGenerator(store)
        self._glossary = GlossaryExtractor(store)

    def generate(
        self,
        persona: str = "developer",
        scope: str = "workspace",
    ) -> OnboardingGuide:
        """Generate a complete onboarding guide."""
        sections: List[GuideSection] = []
        section_id = 0

        # 1. Welcome & overview
        services = [n for n in self._store.all_nodes() if n.get("type") == "Service"]
        section_id += 1
        sections.append(GuideSection(
            section_id=section_id,
            title="项目概览",
            content=f"本工作区包含 {len(services)} 个服务。以下是快速了解项目的步骤。",
            action_items=["阅读 README.md", "了解项目目录结构"],
        ))

        # 2. Architecture tour
        tour = self._tour_gen.generate_tour(persona=persona, scope=scope)
        section_id += 1
        sections.append(GuideSection(
            section_id=section_id,
            title="架构导览",
            content=f"共 {len(tour.steps)} 个步骤，按依赖顺序了解系统架构。",
            action_items=[f"步骤 {s.step_id}: {s.title}" for s in tour.steps[:5]],
        ))

        # 3. Key entry points
        endpoints = [n for n in self._store.all_nodes() if n.get("type") == "Endpoint"]
        section_id += 1
        sections.append(GuideSection(
            section_id=section_id,
            title="API 入口点",
            content=f"系统暴露 {len(endpoints)} 个 HTTP 端点。",
            related_nodes=[e.get("id", "") for e in endpoints[:10]],
            action_items=["尝试调用核心 API", "查看 Swagger/OpenAPI 文档"],
        ))

        # 4. Glossary
        glossary = self._glossary.extract(limit=20)
        section_id += 1
        sections.append(GuideSection(
            section_id=section_id,
            title="项目术语表",
            content=f"以下是项目中常见的 {len(glossary)} 个术语。",
            action_items=[f"{t.term} ({t.category})" for t in glossary[:10]],
        ))

        # 5. First tasks
        section_id += 1
        first_tasks = self._suggest_first_tasks(persona)
        sections.append(GuideSection(
            section_id=section_id,
            title="推荐的第一步",
            content="以下是推荐的上手任务。",
            action_items=first_tasks,
        ))

        return OnboardingGuide(
            guide_id=f"guide:{scope}:{persona}",
            persona=persona,
            sections=sections,
            glossary_terms=[t.to_dict() for t in glossary],
        )

    def _suggest_first_tasks(self, persona: str) -> List[str]:
        """Suggest first tasks based on persona."""
        if persona == "developer":
            return [
                "运行项目测试套件",
                "在本地启动核心服务",
                "修改一个简单的 bug 或添加日志",
                "提交第一个 PR",
            ]
        elif persona == "architect":
            return [
                "审查服务间依赖关系",
                "检查配置管理策略",
                "评估消息队列使用模式",
            ]
        elif persona == "product":
            return [
                "了解核心业务流程",
                "查看 API 端点列表",
                "理解数据流向",
            ]
        elif persona == "tester":
            return [
                "了解测试框架和覆盖率",
                "识别核心业务流程的测试用例",
                "检查 MQ 消费者的幂等性测试",
            ]
        return ["开始探索项目结构"]
