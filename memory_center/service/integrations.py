"""统一服务的宿主 Skill 安装与配置模板，不改动其它插件。"""
import argparse
import json
import shutil
from pathlib import Path

TARGETS = ('agents', 'codex', 'claude', 'dsh', 'gemini', 'workbuddy')


def install_skills(home, targets, force=False):
    source = Path(__file__).resolve().parents[1] / 'resources/wiki'
    installed = []
    for name in targets:
        if name not in TARGETS:
            raise ValueError('不支持的宿主：' + name)
        destination = Path(home) / ('.' + name) / 'skills/wiki'
        existing = destination / 'SKILL.md'
        if existing.exists() and existing.read_bytes() != (source / 'SKILL.md').read_bytes():
            if not force:
                raise FileExistsError('已有不同 Skill；明确使用 --force 才更新')
            shutil.copy2(existing, existing.with_suffix('.md.before-v5'))
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / 'SKILL.md', existing)
        if name == 'codex':
            (destination / 'agents').mkdir(exist_ok=True)
            shutil.copy2(source / 'agents/openai.yaml', destination / 'agents/openai.yaml')
        installed.append(str(destination))
    return installed


def main():
    parser = argparse.ArgumentParser(description='安装统一 Wiki Skill，输出 MCP 配置模板')
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--target', choices=TARGETS, action='append')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    paths = install_skills(args.home, args.target or ['agents', 'codex', 'claude', 'workbuddy'], args.force)
    print(json.dumps({'installed': paths, 'mcpServers': {'memory-center': {'command': 'memory-center-mcp', 'args': [],
          'env': {'MEMORY_CENTER_URL': 'http://127.0.0.1:8765/mcp'}}}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
