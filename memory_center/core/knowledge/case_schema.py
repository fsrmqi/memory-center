"""L1 case atom 的 schema 化定义与写作纪律(设计参考 OpenViking MemoryTypeSchema)。

OpenViking 把每种记忆类型定义为 YAML schema:类型化字段 + 逐字段合并算子 +
内容模板;提取产出必须符合模板三段式纪律(Situation/Approach/Reflect)。
Memory Center 借鉴其结构与纪律,但不引入 LLM:模板作为宿主 Agent 的写作
规范随 suggest_case 返回,字段校验用纯函数完成。

- 内置 schema 在本模块中以数据结构声明(与 governance DEFAULT_RULES 同风格);
- workspace 可用 `rules/case-schemas.yaml` 覆盖/新增(字段定义同构);
- `case_writing_guide()` 把 schema 渲染为宿主可读的写作指南;
- `validate_case_draft()` 在 record_case/consolidation approve 前做有界校验;
- `case_field_ops()` 提供字段 -> 合并算子映射,供 merge_case_record 使用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

import yaml

from memory_center.core.foundation.merge_ops import MergeOp, merge_case_record
from memory_center.core.storage.workspace import WorkspaceStore

CASE_SCHEMA_FILENAME = "case-schemas.yaml"
DEFAULT_CASE_TYPE = "engineering_case"


@dataclass(frozen=True)
class CaseField:
    name: str
    field_type: str  # string | string_list | int | bool
    op: MergeOp
    required: bool = False
    description: str = ""
    max_items: int = 30
    max_chars: int = 2000


@dataclass(frozen=True)
class CaseSchema:
    case_type: str
    description: str
    fields: tuple[CaseField, ...]
    content_template: str = ""
    writing_rules: tuple[str, ...] = ()

    def field(self, name: str) -> CaseField | None:
        return next((item for item in self.fields if item.name == name), None)


# ---------------------------------------------------------------------------
# 内置 schema:继承 MC case 记录的全部既有字段(additive),新字段为
# experience 三段式内容与可累计计数。
# ---------------------------------------------------------------------------

_BUILTIN_FIELDS = (
    CaseField("task", "string", MergeOp.IMMUTABLE, required=True, description="任务主题(作为 case 标识,写定后不修改)"),
    CaseField("projects", "string_list", MergeOp.APPEND, required=True, description="涉及服务列表"),
    CaseField("files", "string_list", MergeOp.APPEND, max_items=30, description="关键文件路径(≤30 条)"),
    CaseField("flow", "string", MergeOp.REPLACE, description="调用/工具链路,箭头串联"),
    CaseField("risk_points", "string_list", MergeOp.APPEND, description="风险点(幂等/契约/迁移等)"),
    CaseField("verified_by", "string_list", MergeOp.APPEND, description="验证人与验证方式"),
    CaseField("source_session_id", "string", MergeOp.IMMUTABLE, description="来源会话"),
    CaseField("source_task_id", "string", MergeOp.IMMUTABLE, description="来源任务空间"),
    CaseField(
        "situation",
        "string",
        MergeOp.REPLACE,
        max_chars=2000,
        description="## Situation — 何时适用:入口条件、用户意图、场景边界(只写条件,不写步骤)",
    ),
    CaseField(
        "approach",
        "string",
        MergeOp.REPLACE,
        max_chars=3000,
        description="## Approach — 怎么做:可执行的肯定步骤,IF/THEN 分支保留;不放负向约束",
    ),
    CaseField(
        "reflect",
        "string",
        MergeOp.REPLACE,
        max_chars=2000,
        description="## Reflect — 别踩什么:硬性禁令、边界条件、失败教训(只放 DON'T)",
    ),
    CaseField("executions", "int", MergeOp.SUM, description="该 case 被复用执行的累计次数"),
    CaseField("successes", "int", MergeOp.SUM, description="复用执行成功的累计次数"),
)

_DEFAULT_WRITING_RULES = (
    "互斥:Approach 只写肯定步骤,Reflect 只写禁令与边界;同一信息不得同时出现在两段。",
    "原子:一条 case 只覆盖一个任务主题;发现写入了第二个意图,立即拆分。",
    "抽象:剥离具体环境 ID、用户名、一次性路径;保留稳定契约名与技术词。",
    "失败转禁令:过程中的错误必须转化为 Reflect 中的负向约束,而不是留在 Approach。",
    "可执行:Approach 用祈使句写给未来执行者;不要写'我做了什么'的过程叙事。",
)

_DEFAULT_TEMPLATE = """# {task}

## Situation
{situation}

## Approach
{approach}

## Reflect
{reflect}

## Evidence
- projects: {projects}
- flow: {flow}
- risk_points: {risk_points}
"""

BUILTIN_CASE_SCHEMA = CaseSchema(
    case_type=DEFAULT_CASE_TYPE,
    description="工程任务经验:一次已验证、可复用的跨服务任务解决模式",
    fields=_BUILTIN_FIELDS,
    content_template=_DEFAULT_TEMPLATE,
    writing_rules=_DEFAULT_WRITING_RULES,
)


class CaseSchemaRegistry:
    """内置 schema + workspace `rules/case-schemas.yaml` 覆盖。"""

    def __init__(self, store: WorkspaceStore | None = None) -> None:
        self._schemas: dict[str, CaseSchema] = {BUILTIN_CASE_SCHEMA.case_type: BUILTIN_CASE_SCHEMA}
        if store is not None:
            self._load_workspace_overrides(store.rules_dir / CASE_SCHEMA_FILENAME)

    def _load_workspace_overrides(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            return
        if not isinstance(data, dict):
            return
        schemas = data.get("schemas")
        if not isinstance(schemas, list):
            return
        for raw in schemas:
            if not isinstance(raw, dict):
                continue
            schema = _parse_schema(raw)
            if schema is not None:
                self._schemas[schema.case_type] = schema

    def get(self, case_type: str = DEFAULT_CASE_TYPE) -> CaseSchema:
        return self._schemas.get(case_type.strip() or DEFAULT_CASE_TYPE, BUILTIN_CASE_SCHEMA)

    def list_types(self) -> list[str]:
        return sorted(self._schemas)


def _parse_schema(raw: dict[str, Any]) -> CaseSchema | None:
    name = str(raw.get("case_type", "") or raw.get("name", "") or "").strip()
    if not name:
        return None
    fields: list[CaseField] = []
    for item in raw.get("fields", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            op = MergeOp(str(item.get("op", "replace")))
        except ValueError:
            op = MergeOp.REPLACE
        fields.append(
            CaseField(
                name=str(item.get("name", "") or "").strip(),
                field_type=str(item.get("type", "string") or "string"),
                op=op,
                required=bool(item.get("required", False)),
                description=str(item.get("description", "") or ""),
                max_items=int(item.get("max_items", 30) or 30),
                max_chars=int(item.get("max_chars", 2000) or 2000),
            )
        )
    if not fields:
        return None
    return CaseSchema(
        case_type=name,
        description=str(raw.get("description", "") or ""),
        fields=tuple(fields),
        content_template=str(raw.get("content_template", "") or ""),
        writing_rules=tuple(str(rule) for rule in (raw.get("writing_rules") or [])),
    )


def load_case_registry(store: WorkspaceStore) -> CaseSchemaRegistry:
    return CaseSchemaRegistry(store)


# ---------------------------------------------------------------------------
# 校验与指南
# ---------------------------------------------------------------------------

_SECTION_HEADER_RE = {
    "situation": re.compile(r"^\s*##?\s*Situation", re.IGNORECASE | re.MULTILINE),
    "approach": re.compile(r"^\s*##?\s*Approach", re.IGNORECASE | re.MULTILINE),
    "reflect": re.compile(r"^\s*##?\s*Reflect", re.IGNORECASE | re.MULTILINE),
}


def validate_case_draft(draft: dict[str, Any], schema: CaseSchema) -> dict[str, Any]:
    """对 case 草稿做纯函数校验,返回 {valid, errors, warnings}。

    校验范围:required 缺失、类型形状、list 条数上限、字符串长度上限、
    三段式段落头。任何失败都不阻断既有调用方——record_case 侧把 valid=False
    作为可读警告返回,是否继续由调用方决定。
    """
    errors: list[str] = []
    warnings: list[str] = []
    for item in schema.fields:
        value = draft.get(item.name)
        if value is None or value == "" or value == []:
            if item.required:
                errors.append(f"缺少必填字段 {item.name}")
            continue
        if item.field_type == "string_list":
            if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
                errors.append(f"字段 {item.name} 必须是字符串列表")
                continue
            if len(value) > item.max_items:
                errors.append(f"字段 {item.name} 超过 {item.max_items} 条上限(当前 {len(value)})")
        elif item.field_type == "string":
            if not isinstance(value, str):
                errors.append(f"字段 {item.name} 必须是字符串")
                continue
            if len(value) > item.max_chars:
                warnings.append(f"字段 {item.name} 超过建议长度 {item.max_chars}(当前 {len(value)}),建议压缩")
            if item.name in _SECTION_HEADER_RE and value.strip() and not _SECTION_HEADER_RE[item.name].search(value):
                errors.append(f"字段 {item.name} 必须以 ## {item.name.capitalize()} 段落头开头(三段式纪律)")
        elif item.field_type == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"字段 {item.name} 必须是整数")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def case_field_ops(schema: CaseSchema) -> dict[str, str]:
    """字段 -> 合并算子值映射,供 merge_case_record 使用。"""
    return {item.name: item.op.value for item in schema.fields}


def case_writing_guide(schema: CaseSchema, *, include_template: bool = True) -> dict[str, Any]:
    """把 schema 渲染为宿主 Agent 可读的写作指南(suggest_case 附带返回)。"""
    guide: dict[str, Any] = {
        "case_type": schema.case_type,
        "description": schema.description,
        "fields": [
            {
                "name": item.name,
                "type": item.field_type,
                "op": item.op.value,
                "required": item.required,
                "description": item.description,
            }
            for item in schema.fields
        ],
        "writing_rules": list(schema.writing_rules),
    }
    if include_template and schema.content_template:
        guide["content_template"] = schema.content_template
    return guide


def merge_case_with_schema(
    base: dict[str, Any],
    updates: dict[str, Any],
    schema: CaseSchema,
) -> dict[str, Any]:
    """按 schema 算子合并 case 记录的便捷封装。"""
    return merge_case_record(base, updates, case_field_ops(schema))


__all__ = [
    "CASE_SCHEMA_FILENAME",
    "DEFAULT_CASE_TYPE",
    "BUILTIN_CASE_SCHEMA",
    "CaseField",
    "CaseSchema",
    "CaseSchemaRegistry",
    "load_case_registry",
    "validate_case_draft",
    "case_field_ops",
    "case_writing_guide",
    "merge_case_with_schema",
]
