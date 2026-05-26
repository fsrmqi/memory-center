"""Memory Center host integration hooks — declarative lifecycle event mapping."""
from .spec import load_hooks_config, ensure_default_hooks  # noqa: F401
from .runner import run_hook  # noqa: F401