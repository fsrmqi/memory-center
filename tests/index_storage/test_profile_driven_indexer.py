"""Profile-driven indexer behaviour (declarative extraction + service registry).

These tests pin the openness contract of the indexer:

- With **no** profile the indexer stays neutral: Spring's public
  ``spring.cloud.stream.bindings`` convention is still parsed, but the
  ``custom_kafka_consumers`` mapping is empty (no private MQ namespace is
  hard-coded anywhere in the code).
- A private MQ namespace is supported purely through **data**
  (``MEMORY_CENTER_PROFILE`` pointing at a YAML profile with
  ``config_extractors``), with no code change and no code fork.
- ``parse_feign_clients`` decides "service name vs. class name" from the
  service names registered in ``workspace.yaml`` instead of a hard-coded
  private prefix.
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.foundation.models import JavaSymbol
from memory_center.core.indexing.reindex import parse_feign_clients, parse_yaml_config
from memory_center.core.profiles import load_profile, resolve_profile

# A config file that mixes one neutral Spring convention with one bespoke
# namespace that only a profile may know about.
APPLICATION_YML = """\
spring:
  cloud:
    stream:
      bindings:
        orderCreated-in-0:
          destination: order-created
acme:
  mq:
    consumers:
      orderCreated:
        topic: order-created
      orderCancelled:
        topic: order-cancelled
"""


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _profile_with_extractors(path: Path, *, extra_output: str = "") -> Path:
    """Write a profile YAML declaring declarative MQ extraction rules."""
    extra = ""
    if extra_output:
        extra = (
            "  - id: noise\n"
            f"    root: [\"acme\", \"mq\", \"consumers\"]\n"
            "    value_key: topic\n"
            f"    output: \"{extra_output}\"\n"
        )
    text = (
        "name: acme\n"
        "config_extractors:\n"
        "  - id: acme-kafka-consumers\n"
        "    root: [\"acme\", \"mq\", \"consumers\"]\n"
        "    value_key: \"topic\"\n"
        "    output: \"custom_kafka_consumers\"\n"
        + extra
    )
    return _write(path, text)


# ── Declarative MQ extraction ──────────────────────────────────────────────


def test_default_profile_keeps_custom_kafka_consumers_empty(tmp_path: Path, monkeypatch) -> None:
    """No profile ⇒ neutral degradation: row shape intact, nothing extracted."""
    monkeypatch.delenv("MEMORY_CENTER_PROFILE", raising=False)
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path)

    # Return shape is a closed contract — all three keys always present.
    assert set(row) == {"values", "stream_bindings", "custom_kafka_consumers"}
    assert row["custom_kafka_consumers"] == {}
    # The neutral Spring convention still works without any profile.
    assert row["stream_bindings"] == {"orderCreated-in-0": "order-created"}
    assert row["values"]["acme.mq.consumers.orderCreated.topic"] == "order-created"


def test_profile_config_extractor_supplies_private_namespace(tmp_path: Path, monkeypatch) -> None:
    """A profile (data, not code) plugs in a bespoke MQ namespace."""
    profile = _profile_with_extractors(tmp_path / "acme-profile.yaml")
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(profile))
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path)

    assert row["custom_kafka_consumers"] == {
        "orderCreated": "order-created",
        "orderCancelled": "order-cancelled",
    }
    # Neutral conventions keep working alongside the profile rule.
    assert row["stream_bindings"] == {"orderCreated-in-0": "order-created"}


def test_profile_extractor_buckets_merge_later_wins(tmp_path: Path, monkeypatch) -> None:
    """Extractors are merged by ``output`` (later wins); other outputs never leak."""
    profile = _profile_with_extractors(tmp_path / "bucket-profile.yaml", extra_output="reserved_mq")
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(profile))
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path)

    # Only the ``custom_kafka_consumers`` bucket is published (closed row shape).
    assert row["custom_kafka_consumers"] == {
        "orderCreated": "order-created",
        "orderCancelled": "order-cancelled",
    }
    assert "reserved_mq" not in row
    assert set(row) == {"values", "stream_bindings", "custom_kafka_consumers"}


def test_unresolvable_profile_degrades_to_neutral(tmp_path: Path, monkeypatch) -> None:
    """A broken profile pointer must not blank out the neutral Spring extraction."""
    monkeypatch.setenv("MEMORY_CENTER_PROFILE", str(tmp_path / "does-not-exist.yaml"))
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path)

    assert row["custom_kafka_consumers"] == {}
    assert row["stream_bindings"] == {"orderCreated-in-0": "order-created"}


# ── Feign target: registered service name vs. class name ───────────────────

FEIGN_SOURCE = """\
package com.example.order;

@FeignClient(name = "orderApi", url = "https://orders.example.com")
public interface OrderRemoteClient {
    @GetMapping("/orders/{id}")
    String getOrder(String id);
}
"""

UNREGISTERED_FILE = "src/main/java/com/example/order/OrderRemoteClient.java"


def _feign_symbol(file: str = UNREGISTERED_FILE) -> JavaSymbol:
    return JavaSymbol(
        project="demo-order",
        file=file,
        annotations=["FeignClient"],
        interfaces=["OrderRemoteClient"],
    )


def test_feign_registered_service_name_skips_url_fallback() -> None:
    """A name registered in ``workspace.yaml`` is a service, not a class name."""
    clients = parse_feign_clients(
        "demo-order",
        UNREGISTERED_FILE,
        FEIGN_SOURCE,
        _feign_symbol(),
        service_names=frozenset({"orderApi"}),
    )

    assert [client.target_service for client in clients] == ["orderApi"]


def test_feign_unregistered_lowercase_camel_name_falls_back_to_url() -> None:
    """Without a registry match, a class-name-looking target still uses ``url``."""
    clients = parse_feign_clients(
        "demo-order",
        UNREGISTERED_FILE,
        FEIGN_SOURCE,
        _feign_symbol(),
        service_names=frozenset({"acme-order-service"}),
    )

    assert [client.target_service for client in clients] == ["external:https://orders.example.com"]


def test_feign_without_service_names_keeps_historical_behaviour() -> None:
    """``service_names=None`` (legacy callers) behaves exactly as before."""
    clients = parse_feign_clients("demo-order", UNREGISTERED_FILE, FEIGN_SOURCE, _feign_symbol())

    assert [client.target_service for client in clients] == ["external:https://orders.example.com"]


# ── Explicit profile argument (workspace declaration path) ─────────────────


def test_explicit_profile_argument_needs_no_environment(tmp_path: Path) -> None:
    """``parse_yaml_config(profile=...)`` works without any env/profile file.

    This is the path used by the reindex entry point, which resolves the
    workspace's own ``profile:`` declaration and passes it down explicitly.
    """
    profile = load_profile(
        {
            "name": "explicit-acme",
            "config_extractors": [
                {"id": "acme-mq", "root": ["acme", "mq", "consumers"], "value_key": "topic"}
            ],
        }
    )
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path, profile=profile)

    assert row["custom_kafka_consumers"] == {
        "orderCreated": "order-created",
        "orderCancelled": "order-cancelled",
    }


def test_workspace_declared_profile_drives_extraction(tmp_path: Path) -> None:
    """A workspace's own ``profile:`` declaration resolves to a usable profile."""
    profile_path = _profile_with_extractors(tmp_path / "workspace-declared.yaml")
    resolved = resolve_profile(None, workspace_profile=str(profile_path))
    config_path = _write(tmp_path / "application.yml", APPLICATION_YML)

    row = parse_yaml_config(config_path, profile=resolved)

    assert resolved.name == "acme"
    assert resolved.config_extractors
    assert row["custom_kafka_consumers"]["orderCancelled"] == "order-cancelled"
