"""Project matching and FQN inference — extracted from orchestrator/query.py.

Provides reusable project disambiguation logic so it can be used by
both orchestrator and MCP layers without circular imports.
"""
from __future__ import annotations

_GENERIC_COMPONENTS = {
    "api", "app", "web", "back", "front", "open", "cloud", "core",
    "base", "common", "service", "biz", "lib", "sdk", "data",
    "test", "main", "src", "res", "config", "util", "utils",
}

_PACKAGE_STOPWORDS = {
    "cn", "com", "org", "net", "io", "app", "api", "biz", "service",
    "impl", "common", "core", "dto", "vo", "entity", "config", "util",
    "utils", "controller", "mapper", "dao", "repository", "model",
    "bean", "factory", "handler", "listener", "filter", "interceptor",
    "aspect", "annotation", "web", "rest", "rpc", "client", "server",
    "base", "lib", "sdk", "starter", "autoconfigure", "properties",
    "website", "safe", "back", "front", "admin", "manager", "task",
    "job", "schedule", "message", "mq", "cache", "data", "storage",
}


def project_matches(query_project: str, item_project: str) -> bool:
    """Check if a project query matches an item's project name.

    Uses normalized matching: splits on '-' and '_', then checks if the
    query matches the full name, any component (>=4 chars), or a concatenation
    of adjacent components.
    """
    if not query_project or not item_project:
        return False
    q = query_project.lower().strip()
    p = item_project.lower().strip()
    if q == p:
        return True

    p_parts = p.replace("-", "_").split("_")

    # Full component match — only if component is specific enough
    if q in p_parts and q not in _GENERIC_COMPONENTS:
        return True

    # Concatenated adjacent component match (e.g. 'openapi' matches 'open_api')
    for i in range(len(p_parts)):
        for j in range(i + 2, min(i + 5, len(p_parts) + 1)):
            if "".join(p_parts[i:j]) == q:
                return True

    # Hyphenated query match (e.g. 'open-api' matches 'open_api')
    if "-" in q:
        q_parts = q.replace("-", "_").split("_")
        for i in range(len(p_parts)):
            if p_parts[i:i + len(q_parts)] == q_parts:
                return True

    return False


def infer_project_from_fqn(fqn: str, known_projects: list[str]) -> str:
    """Try to infer the project name from a fully-qualified class name.

    E.g.  cn.kaipuyun.cloud.openapi.biz.service.impl.website.safe.FooServiceImpl
    → segments = [cn, kaipuyun, cloud, openapi, biz, service, impl, ...]
    → try matching 'openapi' against known project names.
    """
    parts = fqn.replace("#", ".").split(".")
    segments = [p for p in parts[:-1] if p and p[0].islower()]

    best_proj = ""
    best_score = 0

    for seg in reversed(segments):
        if len(seg) < 3 or seg in _PACKAGE_STOPWORDS:
            continue
        candidates: list[tuple[str, int]] = []
        for proj in known_projects:
            proj_lower = proj.lower()
            proj_parts = proj_lower.replace("-", "_").split("_")

            if seg == proj_lower:
                score = 100
            elif seg in proj_parts:
                score = 80
            else:
                matched = False
                for i in range(len(proj_parts)):
                    for j in range(i + 2, min(i + 5, len(proj_parts) + 1)):
                        if "".join(proj_parts[i:j]) == seg:
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    score = 70
                elif seg in proj_lower:
                    score = 50
                else:
                    continue
            candidates.append((proj, score))

        if candidates:
            # Prefer unique matches
            if len(candidates) == 1:
                return candidates[0][0]
            best_candidate = max(candidates, key=lambda x: x[1])
            if best_candidate[1] > best_score:
                best_score = best_candidate[1]
                best_proj = best_candidate[0]

    return best_proj
