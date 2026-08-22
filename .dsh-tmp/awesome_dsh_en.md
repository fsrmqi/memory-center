# Awesome DeepSeek Harness (DSH) Plugin [![Awesome](https://awesome.re/badge.svg)](https://awesome.re) ![awesome · DSH plugin](https://awesome-dsh-plugin.com/badge.svg) ![plugin count](https://img.shields.io/endpoint?url=https%3A%2F%2Fawesome-dsh-plugin.com%2Fcount.json)

[![Awesome DSH Plugin](https://awesome-dsh-plugin.com/banner-en.png)](https://awesome-dsh-plugin.com)

English | [中文](README.zh.md)

> A curated list of plugins for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`).

DeepSeek Harness is DeepSeek's open-source agent harness — a runnable coding agent (Web and headless), built on a framework where everything is a plugin: models, tools, sandboxes, session storage, UI, even the agent loop itself. Plugins can extend the official coding agent, swap out its core parts, or assemble something entirely different.

This list collects community plugins that are installable via `dsh plugin add` (each declares a `dsh.bundle` manifest). [PRs welcome](#contributing).

> 🛒 **Recommended: [dsh-market](https://github.com/dsh-market/dsh-market#readme)** (optional) — the plugin market inside DeepSeek Harness, with every plugin on this list. Simple, friendly UI: one-click plugin install and upgrade, one-click theme switching:

```sh
dsh plugin --profile web add dshmarket
```

<a href="https://raw.githubusercontent.com/dsh-market/dsh-market/main/assets/demo-en.png"><img src="https://raw.githubusercontent.com/dsh-market/dsh-market/main/assets/demo-en.png" width="320" alt="dsh-market plugin browser inside DeepSeek Harness Settings: searchable plugin cards with one-click Install, category filters and a Themes tab"></a>

<sub><i>The plugin market inside Settings — click to enlarge.</i></sub>

> 💡 Prefer chat? [dsh-find-plugin](https://github.com/awesome-dsh-plugin/dsh-find-plugin#readme) lets your agent find plugins for you (`dsh plugin --profile web add dsh-find-plugin`).

> ℹ️ **On desktop clients.** This list is client-agnostic. A plugin is listed because it follows the official protocol — it declares a `dsh.bundle` manifest and installs with `dsh plugin add` — not because it adapts to any particular client.
>
> We're talking with `anywhere-labs/deepseek-harness-desktop` about working together again; we'll update this note as that progresses. Whatever comes of it, the listing rule stays as it is: adapting to any particular client is not a condition of being listed, and no plugin will be removed or demoted for not doing so.
>
> Clients worth a look: [dsh-desktop](https://github.com/dataelement/dsh-desktop) and [deepseek-harness-desktop](https://github.com/hairyf/deepseek-harness-desktop) — both ship dsh-market built in, so everything on this list is one click away. Any other good third-party client works too.

> [!WARNING]
> Installing a plugin runs third-party code on your machine with your own permissions — it can read your files, use your credentials, and reach the network. Tool approvals don't sandbox plugin code. Being on this list is not a security review: check the source before you install, and try unfamiliar plugins somewhere that doesn't hold your keys. See the full disclaimer at the bottom of this page.

<details>
<summary><b>What it takes to be listed here</b></summary>

An entry is added when the plugin installs with `dsh plugin add`, does what its one-line description says, sits in the right category, and is maintained. Every submission is checked against its own source before merging — if a description claims "46 tools", someone counts them.

That is the whole bar. **This list doesn't rank plugins or judge their quality, and we don't want to.** Plenty of good software will never appear here, and a slot here proves nothing beyond meeting those rules. They exist so that whatever you pick installs and behaves the way the line said it would.

A listing isn't permanent either: entries whose repos go away, stop being maintained, or turn out to be broken get removed. Full criteria and the review checklist: [how submissions are reviewed](contributing.md#how-submissions-are-reviewed--收录如何评审).

</details>

## Contents

<!-- BEGIN TOC -->
- [Plugins](#plugins)
  - [UI Enhancements](#ui-enhancements)
  - [Usage & Billing](#usage--billing)
  - [Themes & Appearance](#themes--appearance)
  - [Models & Providers](#models--providers)
  - [Identity & Communication](#identity--communication)
  - [Sessions & Messages](#sessions--messages)
  - [Memory](#memory)
  - [Tools & Capabilities](#tools--capabilities)
  - [Browser & Web](#browser--web)
  - [Vision & Multimodal](#vision--multimodal)
  - [Voice & Audio](#voice--audio)
  - [Docs & Rendering](#docs--rendering)
  - [Skills](#skills)
  - [Workflow & Automation](#workflow--automation)
  - [Git & Code Review](#git--code-review)
  - [Notifications & Integrations](#notifications--integrations)
  - [Development & Runtime](#development--runtime)
  - [Security & Permissions](#security--permissions)
  - [Remote & Mobile](#remote--mobile)
  - [Plugin Markets & Managers](#plugin-markets--managers)
  - [Just for Fun](#just-for-fun)
- [Badge](#badge)
- [Disclaimer](#disclaimer)
<!-- END TOC -->

## Plugins

<!-- BEGIN PLUGINS -->
### UI Enhancements

- [01Virex/dsh-status-rotator](https://github.com/01Virex/dsh-status-rotator) - Replaces the "Deep diving..." turn-status label with rotating meme-worthy phrases, with typewriter and gradient effects.
- [0xsline/dsh-spotlight](https://github.com/0xsline/dsh-spotlight) - Keyboard-first command palette for the DSH Web UI.
- [1070296335-create/dph-taskboard](https://github.com/1070296335-create/dph-taskboard) - Session-based task board in the sidebar: drag sessions into todo/doing/review/done columns, create sessions with model and reasoning-effort selection, trash with restore, notes, export/import.
- [13071301808/dsh-composer-expand](https://github.com/13071301808/dsh-composer-expand) - Composer expand/collapse toggle for the Web UI: a ⬆/⬇ button in the composer tool row grows the input to a tall 70vh writing view for long drafts.
- [2768651338/dsh-effort-slider](https://github.com/2768651338/dsh-effort-slider) - A Claude Code-style reasoning-effort slider for the DSH Web UI: stepless drag, snap-on-release, a WebGL fire trail, and real, working thinking-effort control for any custom third-party model or provider.
- [2nd1st/dsh-plugin-open-app](https://github.com/2nd1st/dsh-plugin-open-app) - Runs open-mcp-apps inside DSH: every MCP app gets its own sidebar container with a separate workspace, session, and App mode, an agent status strip under the app, and inline app rendering in ordinary chats.
- [a1073097082/dsh-model-search](https://github.com/a1073097082/dsh-model-search) - Adds searchable filtering to the model selector by provider, model name, and model ID; spaces act as wildcards.
- [a179-sanae/dsh-auto-collapse](https://github.com/a179-sanae/dsh-auto-collapse) - Codex-style workflow auto-collapse: finished turns fold into a single "processed in Xs" row leaving only the final answer; tool calls and think blocks collapse into live-summary chips that follow streaming; expand level by level, fully reversible on uninstall.
- [a735624258/dsh-skill-picker](https://github.com/a735624258/dsh-skill-picker) - WorkBuddy-style skill picker: a button beside the composer opens a searchable list of installed skills; picking one inserts the official /skill-name gesture, so the skill loads with your message.
- [a903067276-rgb/dsh-file-mentions](https://github.com/a903067276-rgb/dsh-file-mentions) - Clickable file paths in DSH replies: Codex-style inline open, reveal in file manager, and a mentioned-files chip list at the turn tail.
- [a903067276-rgb/dsh-file-upload](https://github.com/a903067276-rgb/dsh-file-upload) - One upload button plus drag-and-drop files into the conversation as local paths: save to the project's uploads/, path text into the input box, works with any vision tool.
- [a903067276-rgb/dsh-hud](https://github.com/a903067276-rgb/dsh-hud) - HUD status panel: Git status, MCP servers, skills, model and token usage in a floating side panel.
- [a903067276-rgb/dsh-plan-switch](https://github.com/a903067276-rgb/dsh-plan-switch) - One-click enter/exit Plan mode for the DSH web input bar, a quick-click shortcut for /plan.
- [AcidGr/dsh-web-mobile-fix](https://github.com/AcidGr/dsh-web-mobile-fix) - Mobile layout fixes for the Web UI on narrow screens: full-screen settings panel, one-row plugin nav, full-screen sidebar, centered popups, icon-only session-log button.
- [Aik358/dsh-anchored-monitor](https://github.com/Aik358/dsh-anchored-monitor) - A whip for DeepSeek V4 Pro: it watches the reasoning fingerprint of every thinking block and pulls the model back when it slips from focused "We will / I will" mode into scattered "let me" mode.
- [AikenFra/dsh-alive](https://github.com/AikenFra/dsh-alive) - Zero-token online status indicator for the DeepSeek Harness web UI: an always-visible online/offline dot in the conversation header, auto-refreshed every 15 seconds with no LLM calls.
- [AKIRACOD/dsh-drag-and-drop](https://github.com/AKIRACOD/dsh-drag-and-drop) - File-drag fork: drop documents as removable chips above the composer, send without typing.
- [AKS1st/dsh-sysmon](https://github.com/AKS1st/dsh-sysmon) - System status floating widget: live CPU/memory/disk usage in the bottom-right corner of the DSH Web UI with threshold colour warnings.
- [AlexYin-Tongji/dsh-ui-enhancer](https://github.com/AlexYin-Tongji/dsh-ui-enhancer) - Desktop-style UI enhancements for the DSH Web client: adaptive wallpapers, a desktop pet companion with an activity feed and feeding economy, @file workspace references, and the resizable file/preview right panel.
- [alingalingling/ui-status-label](https://github.com/alingalingling/ui-status-label) - Customize the "deep diving" thinking status label to anything you like.
- [anitman/dsh-plugin-video-player](https://github.com/anitman/dsh-plugin-video-player) - TikTok-style video feed in a floating sidebar window: swipe local or SMB-NAS folders, or paste online video URLs (yt-dlp, bilibili/YouTube, cookies.txt login state); the window auto-fits the video aspect ratio, with fullscreen, drag-resize, Range streaming and an agent video-queue endpoint.
- [anneheartrecord/dsh-desk-pet](https://github.com/anneheartrecord/dsh-desk-pet) - macOS desk pet that lives outside the DSH page: a real always-on-top window that clears fullscreen Spaces, six states driven by local DSH, a native right-click menu with quiet mode and a session list, and a bundled skill that turns one photo into a full eighteen-pose skin on your own image tool and credentials; system Python and ctypes, no Electron and no dependencies.
- [AppliedYuu/dsh-WallpaperAndCost](https://github.com/AppliedYuu/dsh-WallpaperAndCost) - Merged plugin: wallpaper customization (original-resolution uploads, crop editor, per-area opacity, MP4/WebM dynamic wallpapers) + Steam Workshop wallpaper extraction (parses scene.pkg/.tex via a bundled Python script, preview/