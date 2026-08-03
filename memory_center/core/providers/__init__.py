"""可选外部证据提供者；只读、可诊断且不持久化外部结果。"""

from .gitnexus import GitNexusProvider

__all__ = ["GitNexusProvider"]
