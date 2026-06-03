"""V3 matching layer — project matching, symbol resolution, intent detection."""

from .project import project_matches, infer_project_from_fqn

__all__ = ["project_matches", "infer_project_from_fqn"]
