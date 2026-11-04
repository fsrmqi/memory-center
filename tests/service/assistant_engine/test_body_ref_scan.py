"""验证 assistant_admin/validate 的正文 phantom 引用检测（body-ref）。

只读测试：用临时目录构造一个引用了不存在文件的索引，确认被抓到；
不触碰真实 wiki。
"""
import tempfile
from pathlib import Path

from memory_center.platform.assistant import core


def test_body_ref_phantom_caught():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 受治理位置：工作/<公司>/索引.md
        idx = root / "工作" / "测试公司" / "索引.md"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(
            "---\n"
            "title: 测试公司索引\n"
            "module: system\n"
            "owner: 测试用户\n"
            "created: 2026-08-20\n"
            "updated: 2026-08-20\n"
            "version: v1.0\n"
            "status: 生效\n"
            "tags: [索引]\n"
            "related: [模块注册表.md]\n"
            "---\n\n"
            "# 测试公司 — 索引\n\n"
            "## 文件\n\n"
            "- `_项目-Phantom.md` — 不存在的幽灵引用\n"
            "- `_项目-Real.md` — 真实存在\n",
            encoding="utf-8",
        )
        (idx.parent / "_项目-Real.md").write_text("---\ntitle: real\n---\n", encoding="utf-8")

        r = core.validate(root)
        body_refs = [b for b in r["broken"] if b.get("kind") == "body-ref"]
        phantom = [b for b in body_refs if b["ref"] == "_项目-Phantom.md"]
        real = [b for b in body_refs if b["ref"] == "_项目-Real.md"]
        assert phantom, f"应抓到 phantom 引用，实际 broken={r['broken']}"
        assert not real, f"真实存在的文件不应报错，实际={real}"
        print("✅ body-ref 检测通过：phantom 被抓、real 被放过")
        print("   broken:", r["broken_count"], "governed:", r["governed_markdown_count"])


def test_body_ref_ignores_placeholder_and_title():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        idx = root / "工作" / "测试公司" / "索引.md"
        idx.parent.mkdir(parents=True, exist_ok=True)
        idx.write_text(
            "---\n"
            "title: 测试公司索引\nmodule: system\nowner: 测试用户\n"
            "created: 2026-08-20\nupdated: 2026-08-20\nversion: v1.0\nstatus: 生效\n"
            "tags: [索引]\nrelated: [模块注册表.md]\n"
            "---\n\n"
            "# 测试\n\n"
            "模板占位 `_客户-<客户名>.md` 应跳过；纯标题 `普通说明` 应跳过；"
            "路径引用 `Sub/存在.md` 若不存在应抓。\n",
            encoding="utf-8",
        )
        r = core.validate(root)
        body_refs = [b for b in r["broken"] if b.get("kind") == "body-ref"]
        refs = {b["ref"] for b in body_refs}
        assert "<客户名>" not in str(refs), f"占位符不应被抓：{refs}"
        assert "普通说明" not in refs, f"纯标题不应被抓：{refs}"
        print("✅ 防误报通过：占位符/纯标题已跳过")


if __name__ == "__main__":
    test_body_ref_phantom_caught()
    test_body_ref_ignores_placeholder_and_title()
    print("\nALL PASS")
