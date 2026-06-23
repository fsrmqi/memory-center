"""Memory Center host integration hooks — declarative lifecycle event mapping."""
from .runner import run_hook  # noqa: F401
from .spec import ensure_default_hooks, load_hooks_config  # noqa: F401
