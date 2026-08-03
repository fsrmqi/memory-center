"""可选外部证据提供者；只读、可诊断且不持久化外部结果。"""

from .evidence import build_external_evidence_ref
from .gitnexus import GitNexusProvider
from .health import ProviderHealthMonitor
from .mcp_bridge import (
    HttpMcpBridgeClient,
    McpBridgeProvider,
    McpProviderPolicy,
    McpToolPolicy,
    bridge_policy_path,
    load_mcp_bridge_policy,
    mcp_bridge_policy_status,
)
from .registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry, ProviderSpec

__all__ = [
    "DEFAULT_PROVIDER_REGISTRY",
    "GitNexusProvider",
    "HttpMcpBridgeClient",
    "McpBridgeProvider",
    "McpProviderPolicy",
    "McpToolPolicy",
    "ProviderHealthMonitor",
    "ProviderRegistry",
    "ProviderSpec",
    "build_external_evidence_ref",
    "bridge_policy_path",
    "load_mcp_bridge_policy",
    "mcp_bridge_policy_status",
]
