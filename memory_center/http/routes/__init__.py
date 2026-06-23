"""HTTP route families used by the local bridge."""

from .analysis import register_analysis_routes
from .workflow import register_workflow_routes
from .workspace import register_workspace_routes

__all__ = [
    "register_analysis_routes",
    "register_workspace_routes",
    "register_workflow_routes",
]
