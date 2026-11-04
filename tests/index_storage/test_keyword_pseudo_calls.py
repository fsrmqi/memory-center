"""Keyword pseudo-call regression anchors (real-workspace-driven).

Each case pins one provable rule from sampling real unresolved calls in
a real workspace: Java statement keywords and type literals can never
be method names or call receivers, so the regex extractor must not emit
call rows for them — while real calls in the same body stay intact.
"""
from __future__ import annotations

from memory_center.core.indexing.java_regex_parser import RegexJavaParser


def _calls(src: str):
    result = RegexJavaParser().parse(src, "Anchor.java")
    return result.method_calls


def _source_with(body: str) -> str:
    return (
        "package com.example;\n"
        "public class Anchor {\n"
        f"    void run() {{\n{body}\n    }}\n}}\n"
    )


KEYWORDS = {"synchronized", "assert", "throw", "class", "new", "return", "instanceof"}


def test_synchronized_block_is_not_a_call():
    """`synchronized (lock) {` — the block header, not an invocation.

    Real-workspace evidence: DateUtil.getDateFormat -> synchronized()
    landed in the unqualified_or_dynamic bucket as a garbage edge.
    """
    calls = _calls(_source_with(
        "        Object lock = new Object();\n"
        "        synchronized (lock) {\n"
        "            helper.tick();\n"
        "        }\n"
    ))
    assert all(c.get("method_name") != "synchronized" for c in calls)
    # the real call inside the block survives
    assert any(c.get("method_name") == "tick" for c in calls)


def test_class_literal_receiver_is_not_a_call():
    """`Foo.class.getName()` — receiver is the type literal `class`.

    Real-workspace evidence: OperateLogRecordConfigureSelector.selectImports
    -> getName() with receiver='class' was unresolvable garbage.
    """
    calls = _calls(_source_with(
        "        String name = Anchor.class.getName();\n"
        "        helper.tick();\n"
    ))
    assert all(c.get("receiver") != "class" for c in calls)
    assert any(c.get("method_name") == "tick" for c in calls)


def test_no_keyword_method_or_receiver_rows_survive():
    """One anchor over the whole keyword set: none of them may appear as
    method_name or receiver in any emitted call row."""
    src = _source_with(
        "        Object lock = new Object();\n"
        "        synchronized (lock) { helper.tick(); }\n"
        "        String n = Anchor.class.getName();\n"
        "        helper.tick();\n"
    )
    for call in _calls(src):
        assert call.get("method_name") not in KEYWORDS
        assert call.get("receiver") not in KEYWORDS


def test_real_qualified_and_chained_calls_still_extracted():
    """Over-filtering guard: ordinary qualified and chained invocations in
    the same body must keep producing call rows with receivers intact."""
    src = _source_with(
        "        OrderRequest req = new OrderRequest();\n"
        "        service.submit(req);\n"
        "        builder.append(\"x\").append(\"y\");\n"
        "        synchronized (builder) { helper.tick(); }\n"
    )
    calls = _calls(src)
    assert any(c.get("receiver") == "service" and c.get("method_name") == "submit" for c in calls)
    assert any(c.get("receiver") == "builder" and c.get("method_name") == "append" for c in calls)
    assert any(c.get("method_name") == "tick" for c in calls)


def test_this_and_super_receivers_are_preserved():
    """`this`/`super` are legitimate receivers (unlike `class`/`new`);
    the keyword filter must not drop them."""
    src = _source_with(
        "        this.validate();\n"
        "        super.finalize();\n"
    )
    calls = _calls(src)
    receivers = {c.get("receiver") for c in calls}
    assert "this" in receivers
    assert "super" in receivers
