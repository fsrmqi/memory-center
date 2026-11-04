"""项目内 TS 路径映射；配置越界、循环继承或歧义均不猜测目标。"""
import json
from pathlib import Path


def jsonc(text):
    output, quoted, escaped, i = [], False, False, 0
    while i < len(text):
        c = text[i]
        if quoted:
            output.append(c)
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
            i += 1
        elif c == '"':
            quoted = True
            output.append(c)
            i += 1
        elif text[i:i+2] == '//':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text[i:i+2] == '/*':
            end = text.find('*/', i+2)
            if end < 0:
                raise ValueError('unterminated comment')
            output.append(' ')
            i = end + 2
        else:
            output.append(c)
            i += 1
    text = ''.join(output)
    output, quoted, escaped = [], False, False
    for i, c in enumerate(text):
        if not quoted and c == ',' and text[i+1:].lstrip().startswith(('}', ']')):
            continue
        output.append(c)
        if quoted:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
    return json.loads(''.join(output))


def alias_stems(root, source, module):
    root = Path(root).resolve()
    directory = (root / source).parent
    while directory.is_relative_to(root):
        config = next((directory / name for name in ['tsconfig.json', 'jsconfig.json'] if (directory / name).is_file()), None)
        if config:
            break
        if directory == root:
            return []
        directory = directory.parent
    else:
        return []
    def load(path, seen):
        path = path.resolve()
        if path in seen or not path.is_relative_to(root) or len(seen) >= 16:
            raise ValueError('configuration boundary')
        value = jsonc(path.read_text(encoding='utf-8'))
        parent = value.get('extends')
        result = {}
        if parent:
            if not isinstance(parent, str) or not parent.startswith('.'):
                raise ValueError('external config')
            inherited = path.parent / parent
            if not inherited.suffix:
                inherited = inherited.with_suffix('.json')
            result = load(inherited, seen | {path})
        options = value.get('compilerOptions', {})
        base = (path.parent / options['baseUrl']).resolve() if 'baseUrl' in options else result.get('base', path.parent)
        result['base'] = base
        if 'paths' in options:
            if not isinstance(options['paths'], dict) or any(not isinstance(k, str) or not isinstance(v, list) or any(not isinstance(t, str) for t in v) for k,v in options['paths'].items()):
                raise ValueError('invalid paths')
            result['paths'] = [(pattern, [(base / target).as_posix() for target in targets])
                               for pattern, targets in options['paths'].items()]
        return result
    try:
        options = load(config, set())
        matches = []
        for pattern, targets in options.get('paths', []):
            if pattern.count('*') > 1:
                continue
            if '*' in pattern:
                left, right = pattern.split('*')
                if not module.startswith(left) or not module.endswith(right):
                    continue
                middle = module[len(left):len(module)-len(right) if right else None]
            elif pattern == module:
                middle = ''
            else:
                continue
            for target in targets:
                path = Path(target.replace('*', middle)).resolve()
                if path.is_relative_to(root):
                    matches.append(path.relative_to(root).as_posix())
        return sorted(set(matches))
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return []
