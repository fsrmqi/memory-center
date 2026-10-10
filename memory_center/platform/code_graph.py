"""服务 generation 的通用代码事实；稳定文件身份、导入绑定、保守调用解析。"""
import hashlib
import json
import posixpath
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from memory_center.core.indexing.language_registry import get_language_spec_for_extension
from memory_center.core.indexing.structural_parser import TreeSitterStructuralParser
from memory_center.platform.parse_cache import ParseCache, decode_structural, encode_structural

# 子进程内按语言缓存解析器；tree-sitter 解析器构造相对昂贵，
# 每个文件重建会让池化收益被构造开销吃掉。
_CHILD_PARSERS: dict[str, TreeSitterStructuralParser] = {}


def parse_file_unit(item: tuple[str, str, ParseCache | None]):
    """解析单个文件——工作池任务，故必须是模块级函数（spawn 按引用 pickle）。

    ``item`` 为 ``(relative, abspath, cache)``。返回
    ``(relative, language, status, content_hash, result)``。
    单文件异常在此兜住并返回 ``status='failed:<ExcType>'`` + ``result=None``，
    使一个坏文件只影响自己的覆盖状态，不牵连同批其余文件。
    串行与池化两条路径调用的是同一个函数，这是等价性门槛的落点。

    ``cache`` 非空时按（语言, 内容 sha256）取用解析结果，命中即跳过 tree-sitter；
    命中与未命中返回**逐值相等**的对象，故缓存只影响速度（见 parse_cache 模块）。
    解析器不可用（未装 tree-sitter、语言无绑定）时**不落缓存**——否则「缺绑定」
    会被固化成持久结果，装上绑定后仍读回空解析。
    """
    relative, abspath, cache = item
    spec = get_language_spec_for_extension(Path(abspath).suffix)
    if spec is None:
        return relative, '', 'unsupported', '', None
    try:
        text = Path(abspath).read_text(encoding='utf-8', errors='replace')
        digest = hashlib.sha256(text.encode()).hexdigest()
        parser = _CHILD_PARSERS.get(spec.name)
        if parser is None:
            parser = TreeSitterStructuralParser(spec.name)
            _CHILD_PARSERS[spec.name] = parser
        if cache is not None and parser.available:
            cached = cache.get(spec.name, digest)
            if cached is not None:
                result = decode_structural(cached)
                return relative, spec.name, result.raw.get('parse_status', 'unavailable'), digest, result
        result = parser.parse(text, relative)
        status = result.raw.get('parse_status', 'unavailable') if parser.available else 'unavailable'
        if cache is not None and parser.available:
            cache.put(spec.name, digest, value=encode_structural(result))
        return relative, spec.name, status, digest, result
    except Exception as exc:
        return relative, spec.name, f'failed:{type(exc).__name__}', '', None


def build_code_graph(root, files, progress=None, pool=None, cache=None):
    """构建通用代码图。

    ``pool`` 为 :class:`memory_center.platform.work_pool.WorkPool`；为 ``None``
    或宽度为 1 时就地串行。两条路径产出的 ``units``/``symbols``/``coverage``
    必须逐值相等——``WorkPool.map`` 保持输入顺序，故 ``units`` 的插入顺序也一致，
    下游关系解析的边顺序因此不变。

    ``cache`` 为 :class:`memory_center.platform.parse_cache.ParseCache`；只缓存
    文件级结构事实。跨文件关系（导入绑定落到哪个文件、调用边）留在下面的归并
    阶段每次重算，因此改动文件的影响不会被缓存掩盖。
    """
    units, symbols, coverage = {}, [], {}
    parse_files = [p for p in files if get_language_spec_for_extension(p.suffix) is not None]
    units_input = [(p.relative_to(root).as_posix(), str(p), cache) for p in parse_files]
    if pool is not None and pool.parallel:
        outcomes = pool.map(parse_file_unit, units_input)
    else:
        outcomes = [parse_file_unit(item) for item in units_input]
    for number, (relative, language, status, digest, result) in enumerate(outcomes, 1):
        coverage[relative] = {'language': language, 'status': status, 'hash': digest}
        if result is not None:
            units[relative] = result
            for kind, declarations in [('Class', result.classes), ('Function', result.functions)]:
                for declaration in declarations:
                    key = f'{relative}:{kind}:{declaration.qualified_name}:{declaration.line}'
                    symbols.append({'id': 'symbol_' + hashlib.sha256(key.encode()).hexdigest(), 'type': kind,
                                    'name': declaration.name, 'qualified_name': declaration.qualified_name,
                                    'parent': declaration.qualified_name.rpartition('.')[0] if result.language == 'go' and declaration.kind == 'method' else declaration.parent_qualified_name, 'path': relative,
                                    'line': declaration.line, 'end_line': declaration.end_line,
                                    'language': language, 'module': result.module or '', 'hash': digest})
        if progress:
            progress('parsing', number, len(parse_files), 'files')
    by_file = {path: [] for path in units}
    for symbol in symbols:
        by_file[symbol['path']].append(symbol)

    by_name, by_qualified, by_language_name = defaultdict(list), defaultdict(list), defaultdict(list)
    for symbol in symbols:
        if symbol['type'] == 'Function':
            by_name[(symbol['path'], symbol['name'])].append(symbol)
            by_qualified[(symbol['path'], symbol['qualified_name'])].append(symbol)
            by_language_name[(symbol['language'], symbol['name'])].append(symbol)

    def functions(path, name):
        candidates = by_name[(path, name)] + by_qualified[(path, name)]
        return list({s['id']: s for s in candidates}.values())

    @lru_cache(maxsize=10000)
    def module_files(path, module, language):
        if language in {'typescript', 'tsx', 'javascript', 'vue'}:
            if not module.startswith('.'):
                return []  # 外部包、别名及 re-export 链尚未确认，不做文件名后缀猜测。
            base = posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
            stems = [base, *[base + ext for ext in ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.vue']],
                     *[base + '/index' + ext for ext in ['.ts', '.tsx', '.js', '.jsx']]]
            # 多个候选文件也是歧义，不选择第一个。
            return [p for p in stems if p in units]
        if language == 'python':
            if module.startswith('.'):
                dots = len(module) - len(module.lstrip('.'))
                base = posixpath.dirname(path)
                for _ in range(dots - 1):
                    base = posixpath.dirname(base)
                module = module[dots:]
            else:
                base = ''
            stem = posixpath.join(base, module.replace('.', '/'))
            return [p for p in [stem + '.py', stem + '/__init__.py'] if p in units]
        if language == 'go':
            # 由 go.mod 的模块身份定位本项目包；外部依赖保留未解析。
            directory = (Path(root) / path).parent
            while directory.is_relative_to(root):
                module_file = directory / 'go.mod'
                if module_file.is_file():
                    import re
                    match = re.search(r'^module\s+(\S+)', module_file.read_text(encoding='utf-8'), re.M)
                    if match and (module == match[1] or module.startswith(match[1] + '/')):
                        base = posixpath.normpath(posixpath.join(directory.relative_to(root).as_posix(), module[len(match[1]):].lstrip('/')))
                        if base == '.':
                            base = ''
                        return [p for p, r in units.items() if r.language == 'go' and posixpath.dirname(p) == base]
                if directory == root:
                    break
                directory = directory.parent
        return []

    edges, unresolved = [], []
    if progress:
        progress('relations', 0, len(units), 'files')
    for number, (path, result) in enumerate(units.items(), 1):
        for call in result.calls:
            callers = by_qualified[(path, call.caller_qualified_name)]
            text = call.callee_text
            receiver = call.receiver_text
            if receiver and text.startswith(receiver + '.'):
                name = text[len(receiver) + 1:]
            elif receiver:
                name = text
            elif '.' in text:
                receiver, name = text.rsplit('.', 1)
            else:
                name = text
            candidates, reason = [], 'unresolved'
            if len(callers) == 1:
                caller = callers[0]
                owner = caller['parent']
                bound_receiver = result.raw.get('receivers', {}).get(call.caller_qualified_name)
                if receiver in {'self', 'cls', 'this', bound_receiver} and receiver:
                    candidates = functions(path, owner + '.' + name)
                    reason = 'same_owner'
                elif not receiver:
                    scope = call.caller_qualified_name
                    while True:
                        # 嵌套函数、递归、同级声明；不走同名类成员的全局回退。
                        candidates = functions(path, scope + '.' + name)
                        if candidates or not scope:
                            break
                        scope = scope.rpartition('.')[0]
                    if not candidates:
                        candidates = [s for s in functions(path, name) if not s['parent'] or
                                      (result.language == 'go' and s['parent'] == result.module)]
                    reason = 'lexical_scope'
                    if result.language == 'go' and not candidates:
                        candidates = [s for s in by_language_name[('go', name)] if s['parent'] == result.module and
                                      posixpath.dirname(s['path']) == posixpath.dirname(path)]
                        reason = 'same_package'
                key = receiver or name
                binding_scopes = call.caller_qualified_name.split('.')
                shadowed = any(key in result.raw.get('local_bindings', {}).get('.'.join(binding_scopes[:i]), [])
                               for i in range(1, len(binding_scopes) + 1))
                if shadowed and reason != 'same_owner':
                    candidates = [c for c in candidates if c['qualified_name'].startswith(call.caller_qualified_name + '.')]
                if not candidates and not shadowed:
                    bindings = [b for b in result.raw.get('import_bindings', []) if b['local'] == key]
                    if len(bindings) == 1:
                        binding = bindings[0]
                        target_name = name if binding['namespace'] else binding['symbol']
                        target_paths = module_files(path, binding['module'], result.language)
                        for target_path in target_paths:
                            actual_name = target_name
                            if result.language in {'typescript', 'tsx', 'javascript', 'vue'}:
                                actual_name = units[target_path].raw.get('exports', {}).get(target_name, '')
                            if result.language == 'go' and not target_name[:1].isupper():
                                continue
                            if actual_name:
                                candidates.extend(c for c in functions(target_path, actual_name)
                                                  if not c['parent'] or (c['language'] == 'go' and c['parent'] == c['module']))
                        reason = 'explicit_import'
                if not candidates and not shadowed and result.language == 'java' and receiver:
                    imported = set(result.imports)
                    own_package = caller['qualified_name'].rsplit('.', 2)[0] if '.' in owner else ''
                    candidates = [s for s in by_language_name[('java', name)] if s['parent'].rsplit('.', 1)[-1] == receiver and
                                  (s['parent'] in imported or s['parent'].rpartition('.')[0] == own_package)]
                    reason = 'qualified_type'
            if coverage[path]['status'] != 'parsed':
                candidates = []
            candidates = [c for c in candidates if coverage[c['path']]['status'] == 'parsed']
            if len(callers) == len(candidates) == 1:
                edges.append({'source': callers[0]['id'], 'target': candidates[0]['id'], 'line': call.line,
                              'path': path, 'type': 'CALLS', 'resolution': reason, 'evidence_level': 'INFERRED' if reason == 'qualified_type' else 'EXTRACTED'})
            else:
                unresolved.append({'caller': call.caller_qualified_name, 'callee': text, 'path': path,
                                   'line': call.line, 'reason': 'ambiguous' if len(candidates) > 1 or len(callers) > 1 else 'unresolved'})
        if progress:
            progress('relations', number, len(units), 'files')
    return {'schema': 1, 'symbols': symbols, 'edges': edges, 'unresolved': unresolved, 'coverage': coverage}


def coverage_summary(graph):
    from collections import Counter

    statuses = Counter(value['status'] for value in graph['coverage'].values())
    languages = Counter(value['language'] for value in graph['coverage'].values())
    incomplete = sum(count for status, count in statuses.items() if status != 'parsed')
    return {'languages': dict(languages), 'statuses': dict(statuses), 'files': len(graph['coverage']),
            'complete': incomplete == 0, 'incomplete_files': incomplete,
            'symbol_count': len(graph['symbols']), 'resolved_calls': len(graph['edges']),
            'unresolved_calls': len(graph['unresolved'])}


def claim_boundary(graph, scope_unresolved=(), *, require_no_unresolved=False):
    """判断空结果能否作为否定结论，返回 (是否允许, 原因)。

    只有在覆盖完整、且相关范围内没有未解析调用时，才允许断言“不存在”。动态分派、
    继承/接口分派、匿名回调、外部依赖与跨语言调用都不会进入代码图，因此默认不放行，
    否则调用方会把“未解析”误读成“无调用方”并据此删除代码。
    """
    incomplete = sorted(path for path, value in graph['coverage'].items() if value['status'] != 'parsed')
    if incomplete:
        return False, f'{len(incomplete)} 个文件未完整解析（例如 {incomplete[0]}），覆盖不完整'
    if scope_unresolved:
        return False, f'锚点仍有 {len(scope_unresolved)} 个未解析调用（动态分派或外部依赖等）'
    if require_no_unresolved and graph['unresolved']:
        return False, f'索引范围内仍有 {len(graph["unresolved"])} 个未解析调用，可能隐藏调用方'
    return True, ''


def symbol_fresh(root, symbol):
    try:
        root = Path(root).resolve()
        path = root / symbol['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 1024 * 1024:
            return False
        text = path.read_text(encoding='utf-8', errors='replace')
        return hashlib.sha256(text.encode()).hexdigest() == symbol['hash']
    except OSError:
        return False


def query_code_graph(workspace_file, query, mode, limit=10):
    path = Path(workspace_file).parent / 'code-graph.json'
    if not path.is_file():
        return None  # 旧 generation 仅复用 Java 事实入口，需重新索引启用新图。
    graph = json.loads(path.read_text(encoding='utf-8'))
    symbols = graph['symbols']
    matches = [s for s in symbols if query in {s['id'], s['name'], s['qualified_name'], s['path'] + ':' + s['qualified_name']}]
    if not matches and mode == 'symbol':
        matches = [s for s in symbols if query.lower() in s['qualified_name'].lower()]
    # 锚点缺失时只能主张“符号不存在”，不受未解析调用影响，但仍要求覆盖完整。
    allowed, reason = claim_boundary(graph, (), require_no_unresolved=False)
    result = {'state': 'FOUND' if matches else 'NOT_FOUND', 'symbols': matches[:limit],
              'negative_claim_allowed': False, 'negative_claim_reason': '',
              'truncated': len(matches) > limit, 'coverage': coverage_summary(graph)}
    if mode == 'symbol':
        result['negative_claim_allowed'] = (not matches) and allowed
        result['negative_claim_reason'] = '' if matches else reason
        return result
    if len(matches) != 1:
        result['state'] = 'AMBIGUOUS' if matches else 'NOT_FOUND'
        result['chain'] = []
        result['message'] = '请使用 path:qualified_name 或 symbol id 精确定位' if matches else '当前范围未找到锚点'
        result['negative_claim_allowed'] = (not matches) and allowed
        result['negative_claim_reason'] = '' if matches else reason
        return result
    anchor = matches[0]
    result['anchor'] = anchor
    by_id = {s['id']: s for s in symbols}
    upstream = mode in {'callers', 'analyze'}
    anchor_ids = {anchor['id']}
    if anchor['type'] == 'Class':
        anchor_ids.update(s['id'] for s in symbols if s['path'] == anchor['path'] and
                          s['type'] == 'Function' and s['parent'] == anchor['qualified_name'])
    links = [e for e in graph['edges'] if e['target' if upstream else 'source'] in anchor_ids]
    result['chain'] = [{'symbol': by_id[e['source' if upstream else 'target']], 'call': e} for e in links[:limit]]
    result['unresolved_calls'] = [u for u in graph['unresolved'] if u['path'] == anchor['path'] and
                                  u['caller'] == anchor['qualified_name']][:limit]
    result['truncated'] |= len(links) > limit
    result['state'] = 'FOUND' if links else 'INSUFFICIENT_EVIDENCE'
    result['evidence_level'] = ('INFERRED' if any(e['evidence_level'] == 'INFERRED' for e in links) else 'EXTRACTED') if links else 'AMBIGUOUS'
    # 只有在没有任何直接调用方、且锚点与整个索引范围都没有未解析调用时，才允许否定结论。
    allowed, reason = claim_boundary(graph, result['unresolved_calls'], require_no_unresolved=True)
    result['negative_claim_allowed'] = (not links) and allowed
    result['negative_claim_reason'] = '' if links else reason
    return result

