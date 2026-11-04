"""V3 matching layer — project matching, symbol resolution, intent detection."""

from .project import infer_project_from_fqn, project_matches

__all__ = ["project_matches", "infer_project_from_fqn"]
