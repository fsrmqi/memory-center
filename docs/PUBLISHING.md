# 发布流程 / Publishing

Memory Center **只有一个仓库**，它同时也是公开仓库。开发历史在首次公开时做过一次重写：
公开面从一个干净的起始提交开始，此后所有提交都视为可公开内容。

Memory Center uses **a single repository**, which is also the public one. Its history was
rewritten once at the moment of open-sourcing: the public surface starts from a clean initial
commit, and every commit after it is expected to be publishable.

## 为什么当初重写过一次历史 / Why the history was rewritten once

开源前的 543 个提交里含有公司/工程标识、真实业务示例与内部路线记录。把它们直接公开，
`git log -S` 一条命令就能翻出来。因此采用「一次性重写」而不是「长期双分支」：

- 双分支只在首个公开提交这一步有效；之后任一分支合并，私有提交都会进入公开历史。
- 一次性重写把公开历史压成干净起点，此后不再需要维护第二套发布流程。

Before open-sourcing, the 543-commit history contained company/project identifiers, real
business examples and internal roadmaps. Publishing it as-is would expose them to a single
`git log -S`. The history was therefore rewritten once into a clean starting commit;
long-lived dual branches do not work because the first merge re-exposes private commits.

旧历史保存在本地（见下文「本地备份」），不随仓库发布。

## 日常规则 / Day-to-day rules

1. **提交即公开**：任何进入 `main` 的内容都视为公开内容。提交前自查工程名、真实业务标识、
   个人绝对路径与真实规模数据。
2. **内部资料不入库**：内部路线、实施回执、真实工作区基准与第三方调研放在仓库外的本地目录
   （或独立私有存储），并用 `.gitignore` 确保不会被 `git add -A` 带进来。当前约定目录为
   `docs-internal/`（已忽略）。
3. **示例与生成物**：不提交 `memory_center/service/static/` 构建产物、`examples/**` 下的
   `graph.db` / `index/*.json` / `store.lock`（可用 `memory-center reindex` 重建）。
4. **每轮交付递增 `bN`**，同步包、前端、Compose 与当前版本文档，更新 `docs/CHANGELOG.md`，
   跑全量测试后再推送。
5. **测试前置**：管理页是构建产物，`tests/service/**` 依赖 `memory_center/service/static`
   存在，先 `cd frontend && npm ci && npm run build` 再 `pytest`（CI 同样顺序）。

Every commit on `main` is publishable. Internal roadmaps, receipts, real-workspace benchmarks
and third-party research live outside this repository (currently `docs-internal/`, git-ignored).
Do not commit the admin-page build output or generated example artifacts. Bump `bN` each
delivery, update `docs/CHANGELOG.md`, run the full suite, then push.

## 可选工具：导出干净发布包 / Optional: clean export

`scripts/public_release.sh` 仍保留，用于两种场景：给某次发布导出一个不含内部资料的源码包
（tarball / 只读快照），或在需要「再次从零起步」时生成一个新的干净仓库。日常提交与推送
**不需要**它；`.gitattributes` 的 `export-ignore` 规则只在导出时才生效。

```bash
# 预检：导出到临时目录跑全部门禁，不落盘
scripts/public_release.sh

# 保留导出目录，人工复核文件清单
scripts/public_release.sh --keep --ref HEAD
```

门禁包含：私有标识（工程名/公司名/真实用户名）、真实家目录、凭证模式、内部路径与示例生成物、
`LICENSE`/`NOTICE`/CI 等必备文件、Markdown 相对链接可解析、导出规模概览。任一项不通过则退出码 1，
不影响工作区。

`scripts/public_release.sh` remains available for exporting a clean source tarball or for
starting a brand-new clean repository if that is ever needed. Regular commits and pushes do
not use it; the `export-ignore` rules only apply when exporting.

The dry run fails with exit code 1 when any gate trips and never touches the working tree.

## 本地备份 / Local backup

首次公开时的旧历史保存在本机（不随仓库发布）：

```bash
# 完整历史（含重写前的全部提交）
git bundle verify .dsh-tmp/history-backup/memory-center-all.bundle
# 内部资料
tar tzf .dsh-tmp/history-backup/docs-internal.tar.gz | head
```

恢复方式：`git clone .dsh-tmp/history-backup/memory-center-all.bundle <dir>`。
建议把这两个文件复制到仓库之外的位置（Time Machine / 私有云盘），避免误删。

The pre-rewrite history is kept locally at `.dsh-tmp/history-backup/` (never published):
`memory-center-all.bundle` restores every old commit via
`git clone <bundle> <dir>`, and `docs-internal.tar.gz` holds the internal notes.

## 公开仓的首次设置 / One-time repository settings

仓库转公开后需要人工完成后台配置（Git 无法代办）：

1. Settings → General → Danger Zone → **Change repository visibility → Public**。
2. 确认 About 描述、Topics 与 License 识别（GitHub 应自动识别为 Apache-2.0）。
3. 关闭并删除历史遗留的 dependabot PR 与其分支（如已无用途）。
4. 如需彻底清除重写前遗留的不可达对象缓存，向 GitHub Support 提交一次
   "purge unreachable objects / remove cached commits" 请求。

After flipping the repository to public, finish the one-time setup in GitHub settings:
visibility, About/topics, license detection, closing stale dependabot PRs, and optionally a
support request to purge unreachable pre-rewrite objects.
