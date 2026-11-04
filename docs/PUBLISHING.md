# 发布流程 / Publishing

Memory Center 采用「私有仓 + 公开快照」的双轨模型：私有仓保留完整历史与内部资料，
公开发布时从某个提交导出一棵**脱敏后的树**，作为公开仓库的**首个提交**（不带私有历史）。

Memory Center is developed in a private repository that keeps the full history and the
internal notes; the public repository is an exported, sanitized snapshot of a commit,
published as its own first commit (no private history is carried over).

## 为什么不直接用两条长期分支 / Why not two long-lived branches

双分支只在「首个公开提交」这一步有效：之后任一分支再合并，私有提交都会进入公开历史，
`git log -S` / `git log -p` 仍然能检索到内部路径、真实工程名与回执细节。公开快照从零建历史，
才能保证公开仓不存在私有提交。

Long-lived branches only hide private commits until the first merge; after that the private
history is reachable with `git log -S`. A fresh snapshot repository is the only model that
keeps private commits out of the public repository entirely.

## 唯一开关：`.gitattributes` / The single switch

公开面由仓库根的 `.gitattributes` 中的 `export-ignore` 规则决定，`git archive` 会据此剔除
内部资料（内部文档目录、临时审计目录、代码图谱缓存、示例生成物等）、构建产物与本地配置。
新增内部资料时，**加一条 `export-ignore` 即可**，不需要改发布脚本。

The public surface is defined solely by `export-ignore` entries in the repository-root
`.gitattributes`. Adding internal material only needs one new `export-ignore` line.

## 命令 / Commands

```bash
# 1) 预检：导出到临时目录并跑全部门禁，不落盘（推荐每次发布前先跑）
scripts/public_release.sh

# 2) 保留导出目录，人工复核文件清单
scripts/public_release.sh --keep --ref HEAD

# 3) 生成公开快照仓库（独立历史 + tag v<version>）
scripts/public_release.sh --publish --out ../memory-center-public

# 4) 同时推送到公开远端（首次推送前确认目标仓库为空）
scripts/public_release.sh --publish --out ../memory-center-public \
    --remote git@github.com:<your-org>/memory-center.git
```

预检门禁包含：私有标识（工程名/公司名/真实用户名）、真实家目录、凭证模式、内部路径残留、
`LICENSE`/`NOTICE`/CI 等公开面必备文件、Markdown 相对链接可解析、导出文件规模概览。
任一项不通过则退出码 1，私有仓不受影响。

The dry run fails with exit code 1 when any gate trips, and never touches the private
working tree.

## 版本与发布节奏 / Versioning

1. 在私有仓按 `AGENTS.md` 递增 `bN`，同步包、前端、Compose 与当前版本文档，更新 `docs/CHANGELOG.md`。
2. 全量测试与图变更分析通过后提交。
3. 跑 `scripts/public_release.sh` 预检；通过后 `--publish` 生成快照并推送。
4. 公开仓的 `CHANGELOG` 即用户可见的变更记录；内部路线、回执与基准只留在私有仓，不发布。

## 内部资料 / Internal material

私有仓另有内部资料目录，存放内部路线、实现回执、真实工作区基准与竞品调研，**永不进入公开快照**。
公开仓库只保留 `docs/` 下面向使用者与贡献者的文档、`CHANGELOG` 与 `ADR`。
