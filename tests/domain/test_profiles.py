"""Workspace profile 单元测试 / Unit tests for ``memory_center.core.profiles``.

覆盖 / Covers:

- 空文档与中性默认 / empty documents and neutral defaults;
- 严格解析：未知字段、版本不符、``config_extractors`` 结构错误 / strict parsing;
- 别名命中、未命中与 ``module_alias_until`` 过期 / alias lookup and expiry;
- profile 文件加载与 mtime 缓存 / file loading and mtime-keyed cache;
- 解析优先级：显式 > workspace.yaml ``profile:`` > 环境变量 > 默认 / resolution order;
- 搜索目录与 ``MEMORY_CENTER_PROFILE_DIR`` / search directories;
- ``ConfigExtractor.extract`` 的正常、缺节点与非映射输入 / declarative extraction.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from memory_center.core.profiles import (
    DEFAULT_PROFILE,
    PROFILE_ENV,
    PROFILE_SCHEMA_VERSION,
    ConfigExtractor,
    Profile,
    ProfileError,
    WikiTopology,
    load_profile,
    load_profile_file,
    profile_for_workspace,
    profile_search_dirs,
    resolve_profile,
)

PROFILE_DIR_ENV = "MEMORY_CENTER_PROFILE_DIR"


@pytest.fixture(autouse=True)
def isolated_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real profile env out of every test."""
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    monkeypatch.delenv(PROFILE_DIR_ENV, raising=False)


def write_profile(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def write_workspace(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


class TestNeutralDefault:
    def test_empty_document_is_neutral(self) -> None:
        profile = load_profile({})
        assert profile.name == "default"
        assert profile.version == PROFILE_SCHEMA_VERSION
        assert profile.default_scope is None, "空 profile 不应带默认 scope"
        assert profile.module_aliases == {}, "空 profile 不应内置别名"
        assert profile.module_alias_until is None
        assert profile.module_alias_hint == "", "空 profile 不应带提示文案"
        assert profile.wiki == WikiTopology(), "空 profile 的 Wiki 拓扑应为空"
        assert profile.config_extractors == (), "空 profile 不应内置抽取规则"
        assert profile.weak_tokens == frozenset()

    def test_none_document_returns_default_profile(self) -> None:
        assert load_profile(None) is DEFAULT_PROFILE
        assert DEFAULT_PROFILE.default_scope is None
        assert dict(DEFAULT_PROFILE.module_aliases) == {}
        assert DEFAULT_PROFILE.config_extractors == ()

    def test_empty_profile_consumers_degrade_neutrally(self) -> None:
        profile = DEFAULT_PROFILE
        assert profile.alias_target("order") == "order", "无别名时应原样返回"
        assert profile.alias_active() is False
        assert profile.config_extractors == ()


class TestStrictParsing:
    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(ProfileError, match="未知字段"):
            load_profile({"default_scpoe": "typo"})

    def test_version_mismatch_rejected(self) -> None:
        with pytest.raises(ProfileError, match="version"):
            load_profile({"version": PROFILE_SCHEMA_VERSION + 1})

    def test_config_extractors_must_be_a_list(self) -> None:
        with pytest.raises(ProfileError, match="config_extractors"):
            load_profile({"config_extractors": {"id": "one"}})
        with pytest.raises(ProfileError, match="config_extractors"):
            load_profile({"config_extractors": "one"})

    def test_config_extractor_requires_root_and_id(self) -> None:
        with pytest.raises(ProfileError, match="root"):
            load_profile({"config_extractors": [{"id": "one", "root": []}]})
        with pytest.raises(ProfileError, match="id"):
            load_profile({"config_extractors": [{"root": ["a"]}]})

    def test_invalid_date_rejected(self) -> None:
        with pytest.raises(ProfileError, match="module_alias_until"):
            load_profile({"module_alias_until": "not-a-date"})

    def test_full_document_round_trips(self) -> None:
        profile = load_profile(
            {
                "name": "acme",
                "default_scope": " acme-platform ",
                "module_aliases": {"order": "acme-order-service"},
                "module_alias_until": "2026-12-31",
                "module_alias_hint": "use acme-* modules",
                "wiki": {
                    "documents": ["docs"],
                    "governance_paths": ["docs/governance"],
                    "top_level_dirs": ["services", "docs"],
                    "skip_names": ["node_modules"],
                },
                "config_extractors": [
                    {
                        "id": "acme-kafka-consumers",
                        "root": ["acme", "kafka", "consumers"],
                        "value_key": "topic",
                        "output": "custom_kafka_consumers",
                    }
                ],
                "weak_tokens": ["acme"],
            }
        )
        assert profile.name == "acme"
        assert profile.default_scope == "acme-platform", "default_scope 应去除首尾空白"
        assert profile.module_alias_until == date(2026, 12, 31)
        assert profile.wiki.governance_paths == ("docs/governance",)
        assert profile.wiki.skip_names == frozenset({"node_modules"})
        assert profile.config_extractors[0].output == "custom_kafka_consumers"
        assert profile.weak_tokens == frozenset({"acme"})


class TestAliasResolution:
    def test_alias_hit_and_miss(self) -> None:
        profile = load_profile({"module_aliases": {"order": "acme-order-service", "pay": "acme-pay"}})
        assert profile.alias_target("order") == "acme-order-service"
        assert profile.alias_target("  order  ") == "acme-order-service", "别名匹配应忽略首尾空白"
        assert profile.alias_target("PAY") == "acme-pay", "别名匹配应回退到小写"
        assert profile.alias_target("unknown") == "unknown", "未命中时应原样返回"
        assert profile.alias_target("") == ""

    def test_alias_expires_after_until_date(self) -> None:
        profile = load_profile(
            {"module_aliases": {"order": "acme-order-service"}, "module_alias_until": "2026-12-31"}
        )
        assert profile.alias_target("order", today=date(2026, 12, 31)) == "acme-order-service", "到期日当天仍生效"
        assert profile.alias_target("order", today=date(2027, 1, 1)) == "order", "过期后应原样返回"
        assert profile.alias_active(today=date(2026, 12, 31)) is True
        assert profile.alias_active(today=date(2027, 1, 1)) is False

    def test_alias_without_expiry_never_goes_stale(self) -> None:
        profile = load_profile({"module_aliases": {"order": "acme-order-service"}})
        assert profile.alias_target("order", today=date(2999, 1, 1)) == "acme-order-service"


class TestLoadProfileFile:
    def test_loads_file_and_keyword_name(self, tmp_path: Path) -> None:
        path = write_profile(tmp_path / "acme.yaml", "name: acme\ndefault_scope: acme-platform\n")
        profile = load_profile_file(path)
        assert profile.name == "acme"
        assert profile.default_scope == "acme-platform"

    def test_same_mtime_reuses_cached_profile(self, tmp_path: Path) -> None:
        path = write_profile(tmp_path / "acme.yaml", "default_scope: acme-one\n")
        first = load_profile_file(path)
        assert load_profile_file(path) is first, "同一路径且 mtime 未变时应命中缓存"

    def test_changed_mtime_reloads_file(self, tmp_path: Path) -> None:
        path = write_profile(tmp_path / "acme.yaml", "default_scope: acme-one\n")
        first = load_profile_file(path)
        assert first.default_scope == "acme-one"

        stat = path.stat()
        path.write_text("default_scope: acme-two\n", encoding="utf-8")
        # 保证 mtime_ns 变化，避免文件系统时间精度导致缓存不失效
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        reloaded = load_profile_file(path)
        assert reloaded is not first, "mtime 变化后应重新加载"
        assert reloaded.default_scope == "acme-two"

    def test_missing_and_malformed_files_raise(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileError, match="不存在"):
            load_profile_file(tmp_path / "missing.yaml")
        malformed = write_profile(tmp_path / "bad.yaml", "name: [unclosed\n")
        with pytest.raises(ProfileError, match="YAML"):
            load_profile_file(malformed)


class TestSearchDirsAndNamedLookup:
    def test_search_dirs_honour_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = tmp_path / "custom-profile.d"
        custom.mkdir()
        monkeypatch.setenv(PROFILE_DIR_ENV, str(custom))
        dirs = profile_search_dirs()
        assert dirs[0] == custom, "环境变量目录应排在最前"
        assert dirs[-1] == Path.home() / ".memory-center" / "profile.d"

    def test_search_dirs_fall_back_to_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(PROFILE_DIR_ENV, raising=False)
        assert profile_search_dirs() == (Path.home() / ".memory-center" / "profile.d",)

    def test_named_profile_resolved_from_search_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = tmp_path / "profile.d"
        directory.mkdir()
        write_profile(directory / "acme.yaml", "name: acme\ndefault_scope: acme-platform\n")
        monkeypatch.setenv(PROFILE_DIR_ENV, str(directory))
        assert resolve_profile("acme").default_scope == "acme-platform"

    def test_yml_suffix_is_searched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = tmp_path / "profile.d"
        directory.mkdir()
        write_profile(directory / "acme.yml", "name: acme\n")
        monkeypatch.setenv(PROFILE_DIR_ENV, str(directory))
        assert resolve_profile("acme").name == "acme"


class TestResolveProfilePriority:
    def test_explicit_profile_object_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = tmp_path / "profile.d"
        directory.mkdir()
        write_profile(directory / "env.yaml", "name: from-env\n")
        monkeypatch.setenv(PROFILE_DIR_ENV, str(directory))
        monkeypatch.setenv(PROFILE_ENV, "env")

        explicit = Profile(name="explicit")
        assert resolve_profile(explicit) is explicit, "显式 Profile 对象优先级最高"

    def test_explicit_path_wins_over_workspace_and_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        explicit_path = write_profile(tmp_path / "explicit.yaml", "name: explicit\n")
        workspace_path = write_profile(tmp_path / "workspace-profile.yaml", "name: workspace\n")
        env_path = write_profile(tmp_path / "env-profile.yaml", "name: env\n")
        monkeypatch.setenv(PROFILE_ENV, str(env_path))

        resolved = resolve_profile(str(explicit_path), workspace_profile=str(workspace_path))
        assert resolved.name == "explicit", "显式参数应压过 workspace 与 env"

    def test_workspace_profile_wins_over_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        workspace_path = write_profile(tmp_path / "workspace-profile.yaml", "name: workspace\n")
        env_path = write_profile(tmp_path / "env-profile.yaml", "name: env\n")
        monkeypatch.setenv(PROFILE_ENV, str(env_path))

        resolved = resolve_profile(workspace_profile=str(workspace_path))
        assert resolved.name == "workspace", "workspace.yaml 的 profile 应压过 env"

    def test_env_name_resolves_from_search_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = tmp_path / "profile.d"
        directory.mkdir()
        write_profile(directory / "env.yaml", "name: from-env\n")
        monkeypatch.setenv(PROFILE_DIR_ENV, str(directory))
        monkeypatch.setenv(PROFILE_ENV, "env")

        assert resolve_profile().name == "from-env"

    def test_env_path_is_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_path = write_profile(tmp_path / "env-profile.yaml", "name: env-file\n")
        monkeypatch.setenv(PROFILE_ENV, str(env_path))
        assert resolve_profile().name == "env-file"

    def test_default_when_nothing_is_configured(self) -> None:
        resolved = resolve_profile()
        assert resolved.name == "default"
        assert resolved.default_scope is None
        assert resolved.config_extractors == ()

    def test_missing_explicit_name_fails_loud(self) -> None:
        with pytest.raises(ProfileError, match="未找到 profile"):
            resolve_profile("definitely-not-installed", env={})

    def test_missing_env_name_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(PROFILE_ENV, "definitely-not-installed")
        with pytest.raises(ProfileError, match="未找到 profile"):
            resolve_profile()


class TestProfileForWorkspace:
    def test_workspace_declaration_wins_over_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        directory = tmp_path / "profile.d"
        directory.mkdir()
        write_profile(directory / "acme.yaml", "name: acme\ndefault_scope: acme-platform\n")
        write_profile(directory / "env.yaml", "name: from-env\n")
        monkeypatch.setenv(PROFILE_DIR_ENV, str(directory))
        monkeypatch.setenv(PROFILE_ENV, "env")

        workspace = write_workspace(tmp_path / "workspace.yaml", "root: .\nprofile: acme\n")
        assert profile_for_workspace(workspace).default_scope == "acme-platform"

    def test_missing_workspace_falls_back_to_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_path = write_profile(tmp_path / "env-profile.yaml", "name: from-env\n")
        monkeypatch.setenv(PROFILE_ENV, str(env_path))

        assert profile_for_workspace(tmp_path / "missing" / "workspace.yaml").name == "from-env"

    def test_workspace_without_declaration_falls_back_to_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_path = write_profile(tmp_path / "env-profile.yaml", "name: from-env\n")
        monkeypatch.setenv(PROFILE_ENV, str(env_path))
        workspace = write_workspace(tmp_path / "workspace.yaml", "root: .\nservices: []\n")

        assert profile_for_workspace(workspace).name == "from-env"

    def test_no_workspace_and_no_env_returns_default(self) -> None:
        resolved = profile_for_workspace(None)
        assert resolved.name == "default"
        assert resolved.default_scope is None

    def test_declared_name_not_found_fails_loud(self, tmp_path: Path) -> None:
        workspace = write_workspace(tmp_path / "workspace.yaml", "profile: ghost\n")
        with pytest.raises(ProfileError, match="未找到 profile"):
            profile_for_workspace(workspace)


class TestConfigExtractor:
    def test_extracts_value_key_from_nested_mapping(self) -> None:
        extractor = ConfigExtractor(
            id="acme-kafka-consumers",
            root=("acme", "kafka", "consumers"),
            value_key="topic",
            output="custom_kafka_consumers",
        )
        data = {
            "acme": {
                "kafka": {
                    "consumers": {
                        "orderCreated": {"topic": "order-created"},
                        "orderPaid": {"topic": "order-paid"},
                        "ignored": "not-a-mapping",
                        "noTopic": {"group": "acme"},
                    }
                }
            }
        }
        assert extractor.extract(data) == {
            "orderCreated": "order-created",
            "orderPaid": "order-paid",
        }

    def test_missing_node_returns_empty(self) -> None:
        extractor = ConfigExtractor(id="custom", root=("acme", "kafka", "consumers"))
        assert extractor.extract({}) == {}
        assert extractor.extract({"acme": {}}) == {}
        assert extractor.extract({"acme": {"kafka": {"consumers": None}}}) == {}

    def test_non_mapping_node_returns_empty(self) -> None:
        extractor = ConfigExtractor(id="custom", root=("acme", "kafka", "consumers"))
        assert extractor.extract({"acme": "scalar"}) == {}
        assert extractor.extract({"acme": {"kafka": {"consumers": ["a", "b"]}}}) == {}

    def test_default_value_key_and_output(self) -> None:
        extractor = ConfigExtractor(id="custom", root=("acme",))
        assert extractor.value_key == "topic"
        assert extractor.output == "custom_kafka_consumers"
        assert extractor.extract({"acme": {"entry": {"topic": "t"}}}) == {"entry": "t"}


class TestExampleProfile:
    def test_example_profile_is_loadable(self) -> None:
        path = Path(__file__).resolve().parents[2] / "examples" / "profile" / "profile.example.yaml"
        assert path.is_file(), "示例 profile 应随仓库分发"
        profile = load_profile_file(path)

        assert profile.name == "acme"
        assert profile.version == PROFILE_SCHEMA_VERSION
        assert profile.default_scope == "acme-platform"
        assert profile.module_alias_until == date(2026, 12, 31)
        assert profile.module_alias_hint
        assert profile.wiki.documents == ("docs",)
        assert profile.weak_tokens == frozenset({"acme"})
        assert len(profile.config_extractors) == 1
        assert profile.config_extractors[0].output == "custom_kafka_consumers"

        allowed_on = date(2026, 1, 1)
        expired_on = date(2027, 1, 1)
        assert profile.alias_target("order", today=allowed_on) == "acme-order-service"
        assert profile.alias_target("order", today=expired_on) == "order"
        assert profile.config_extractors[0].extract(
            {"acme": {"kafka": {"consumers": {"orderCreated": {"topic": "order-created"}}}}}
        ) == {"orderCreated": "order-created"}
