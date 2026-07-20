"""C-02: Query Quality regression dataset.

Tests for detect_query_intent() using a regression dataset with
positive and negative examples for each intent type.

Dataset uses generic fixtures — no private project data.
"""
from __future__ import annotations

import pytest

from memory_center.core.retrieval.hybrid import detect_query_intent

# ============================================================
# Regression Dataset
# ============================================================

# Each entry: (query, expected_primary_intent, description)
POSITIVE_EXAMPLES = [
    # feign
    ("ArticleFeignClient", "feign", "Java class name with Feign pattern"),
    ("FeginAutomaticReviewTaskService", "feign", "Typo variant Fegin"),
    ("远程调用 order 服务", "feign", "Chinese keyword 远程调用"),
    ("ArticleFeignClient.getById", "feign", "Dotted Feign class with method"),
    # mq
    ("kafka order-topic consumer", "mq", "Kafka + topic + consumer keywords"),
    ("RocketMQ producer send", "mq", "RocketMQ producer"),
    ("消息队列延迟", "mq", "Chinese keyword 消息队列"),
    # endpoint
    ("/api/users", "endpoint", "Path starting with /"),
    ("UserController", "endpoint", "Controller suffix in Java name"),
    ("api 接口设计", "endpoint", "Chinese keyword 接口"),
    # config
    ("server.port 配置", "config", "Config with Chinese keyword"),
    ("application.yml database.url", "config", "YAML file + dot-separated key"),
    ("spring.datasource.properties", "config", "Properties file reference"),
    # chain
    ("调用链 order-service", "chain", "Chinese keyword 调用链"),
    ("call chain trace", "chain", "English call chain keyword"),
    # class
    ("OrderService", "class", "Java class with Service suffix"),
    ("OrderServiceImpl", "class", "ServiceImpl suffix"),
    ("UserDao", "class", "Dao suffix"),
    ("ArticleMapper", "class", "Mapper suffix"),
    # method
    ("calculateTotal 方法", "method", "Chinese keyword 方法"),
    ("method lookup", "method", "English keyword method"),
]

NEGATIVE_EXAMPLES = [
    # These are easy to misclassify — the correct intent should NOT be the naive guess
    ("ArticleService", "class", "Local Service — NOT feign (no FeignClient annotation)"),
    ("UserClient", "general", "Client suffix without Feign or Service — ambiguous, general"),
    ("getById", "general", "Plain method name without context — should be general"),
    ("/", "general", "Single slash — too generic for endpoint"),
    ("config", "config", "Single keyword — ambiguous but config is correct"),
    ("service", "class", "Single keyword service — maps to class via Java pattern"),
]


# ============================================================
# TestIntentRegression: positive examples
# ============================================================

class TestIntentRegression:
    """Verify detect_query_intent returns correct primary intent for known queries."""

    @pytest.mark.parametrize("query,expected,desc", POSITIVE_EXAMPLES, ids=[e[2] for e in POSITIVE_EXAMPLES])
    def test_positive_intent(self, query: str, expected: str, desc: str):
        result = detect_query_intent(query)
        assert result["primary_intent"] == expected, (
            f"Query: {query!r} ({desc})\n"
            f"Expected: {expected}, Got: {result['primary_intent']}\n"
            f"All intents: {result['all_intents']}"
        )


# ============================================================
# TestIntentNegative: negative / boundary examples
# ============================================================

class TestIntentNegative:
    """Verify tricky queries don't produce wrong high-confidence intents."""

    @pytest.mark.parametrize("query,expected,desc", NEGATIVE_EXAMPLES, ids=[e[2] for e in NEGATIVE_EXAMPLES])
    def test_negative_intent(self, query: str, expected: str, desc: str):
        result = detect_query_intent(query)
        assert result["primary_intent"] == expected, (
            f"Query: {query!r} ({desc})\n"
            f"Expected: {expected}, Got: {result['primary_intent']}\n"
            f"All intents: {result['all_intents']}"
        )


# ============================================================
# TestIntentConfidence: confidence scores are reasonable
# ============================================================

class TestIntentConfidence:
    """Verify that intent detection produces reasonable confidence scores."""

    def test_feign_keyword_high_confidence(self):
        result = detect_query_intent("ArticleFeignClient")
        assert result["all_intents"].get("feign", 0) >= 1.0

    def test_mq_keyword_high_confidence(self):
        result = detect_query_intent("kafka order-topic consumer")
        assert result["all_intents"].get("mq", 0) >= 1.0

    def test_endpoint_path_high_confidence(self):
        result = detect_query_intent("/api/users")
        assert result["all_intents"].get("endpoint", 0) >= 0.8

    def test_general_returns_general(self):
        result = detect_query_intent("xyzzy12345_nonexistent")
        assert result["primary_intent"] == "general"

    def test_cross_service_detection(self):
        result = detect_query_intent("feign 远程调用 order")
        assert result["is_cross_service"] is True

    def test_chain_detection(self):
        result = detect_query_intent("调用链 trace")
        assert result["is_chain_query"] is True


# ============================================================
# TestIntentStability: same query always returns same result
# ============================================================

class TestIntentStability:
    """Verify determinism — same input always produces same output."""

    def test_deterministic_output(self):
        queries = [
            "ArticleFeignClient",
            "/api/users",
            "kafka topic",
            "OrderService",
            "calculateTotal 方法",
        ]
        for query in queries:
            first = detect_query_intent(query)
            second = detect_query_intent(query)
            assert first == second, f"Non-deterministic for: {query}"

    def test_all_intents_subset_of_known(self):
        """All returned intents should be from the known set."""
        known_intents = {"feign", "mq", "endpoint", "config", "chain", "class", "method", "general"}
        queries = [ex[0] for ex in POSITIVE_EXAMPLES + NEGATIVE_EXAMPLES]
        for query in queries:
            result = detect_query_intent(query)
            for intent in result["all_intents"]:
                assert intent in known_intents, f"Unknown intent {intent!r} for query {query!r}"


# ============================================================
# TestQualityScoring: dataset quality metrics
# ============================================================

class TestQualityScoring:
    """Aggregate quality metrics across the regression dataset."""

    def test_all_positive_examples_pass(self):
        """All positive examples must match expected intent — 0% false negatives."""
        failures = []
        for query, expected, desc in POSITIVE_EXAMPLES:
            result = detect_query_intent(query)
            if result["primary_intent"] != expected:
                failures.append((query, expected, result["primary_intent"], desc))
        assert not failures, "False negatives:\n" + "\n".join(
            f"  {q!r}: expected {e}, got {g} ({d})" for q, e, g, d in failures
        )

    def test_all_negative_examples_pass(self):
        """All negative examples must match expected intent — boundary cases held."""
        failures = []
        for query, expected, desc in NEGATIVE_EXAMPLES:
            result = detect_query_intent(query)
            if result["primary_intent"] != expected:
                failures.append((query, expected, result["primary_intent"], desc))
        assert not failures, "Boundary failures:\n" + "\n".join(
            f"  {q!r}: expected {e}, got {g} ({d})" for q, e, g, d in failures
        )

    def test_dataset_coverage(self):
        """Dataset must cover at least 7 intent categories."""
        covered = set()
        for _query, expected, _ in POSITIVE_EXAMPLES:
            covered.add(expected)
        assert len(covered) >= 7, f"Only {len(covered)} intents covered: {covered}"
