"""可选外部证据提供者；只读、可诊断且不持久化外部结果。"""

from .evidence import build_external_evidence_ref
from .gitnexus import GitNexusProvider
from .registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry, ProviderSpec

__all__ = [
    "DEFAULT_PROVIDER_REGISTRY",
    "GitNexusProvider",
    "ProviderRegistry",
    "ProviderSpec",
    "build_external_evidence_ref",
]
