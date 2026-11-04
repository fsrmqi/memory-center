"""全局工作池：项目并发与文件级并发共用同一份 CPU 预算。

设计要点（依据 `docs/benchmarks/V5_SERVICE_INDEX_STAGE_BASELINE.md` 实测）：

1. **只能用进程，不能用线程。** tree-sitter 的 Python 绑定不释放 GIL——
   实测 4 线程仅 1.41×，8 线程比串行**慢 24%**；同规模 8 进程为 2.56×。
   因此本模块只提供 ``spawn`` 进程池，不提供线程池。
2. **预算是全局的，不是每项目一份。** 项目级并发已经是「一项目一子进程」；
   若每个项目再各自开满文件级 worker，总量会变成
   ``max_projects × per_project_workers``。故调用方必须先按并发项目数
   切分预算（见 :func:`share_budget`），把**份额**传给子进程。
3. **单文件失败不得拖垮整池。** worker 内自行兜住异常并返回失败标记，
   由调用方记入覆盖台账；池级崩溃（``BrokenProcessPool``）照旧向上抛出，
   让任务有序失败并保留上一代索引，不静默回退为串行。

传输契约：任务函数必须是**模块级**函数（``spawn`` 按引用 pickle），
参数与返回值都需可 pickle。
"""
from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

# 低于该规模时池的启动与消息往返成本超过收益（单文件解析约 4.6ms）。
MIN_PARALLEL_ITEMS = 32
DEFAULT_CHUNKSIZE = 16


def cpu_budget() -> int:
    """可用 CPU 预算：亲和性掩码 ∩ cgroup v2 配额，下限 1。

    这是项目并发与文件并发**共用的唯一**预算来源；``Jobs.settings``
    的自动取值也走这里，避免两处各算一遍而相互矛盾。
    """
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            cpus = min(cpus, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, int(cpus))


def share_budget(budget: int, concurrent_jobs: int) -> int:
    """把总预算切给单个在跑项目。

    ``concurrent_jobs`` 是**含本任务在内**的并发项目数。切分在任务准入时
    一次性完成：同时只有 1 个项目时它拿到全部预算；4 个项目同时开时
    每个拿四分之一。先完成的项目不会把它们交还的份额让给仍在跑的项目，
    这是刻意的取舍——代价是有上限的，收益是无需跨进程抢占协调。
    """
    return max(1, int(budget) // max(1, int(concurrent_jobs)))


class WorkPool:
    """常驻 ``spawn`` 进程池；宽度由调用方显式传入。

    ``None`` 或 ``width <= 1`` 时退化为就地串行，调用方无需分支。
    """

    def __init__(self, width: int | None, *, kind: str = "parse",
                 min_items: int = MIN_PARALLEL_ITEMS, chunksize: int = DEFAULT_CHUNKSIZE):
        self.width = max(1, int(width or 1))
        self.kind = kind
        self.min_items = max(1, int(min_items))
        self.chunksize = max(1, int(chunksize))
        self._executor: ProcessPoolExecutor | None = None
        self.submitted = 0
        self.completed = 0
        self.serial_fallbacks = 0

    @property
    def parallel(self) -> bool:
        return self.width > 1

    def _executor_for_use(self) -> ProcessPoolExecutor:
        if self._executor is None:
            # spawn 而非 fork：服务进程已有线程与打开的文件描述符，
            # fork 会把这些状态复制进子进程，容易在 SQLite / httpx 上出隐蔽问题。
            self._executor = ProcessPoolExecutor(
                max_workers=self.width,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._executor

    def map(self, fn: Callable[[Any], Any], items: Iterable[Any], *,
            chunksize: int | None = None) -> list[Any]:
        """按输入顺序返回结果；顺序与串行实现一致。

        ``fn`` 必须是模块级函数。池不可用或规模过小时就地串行——
        串行路径与池路径必须产出完全相同的值，这是增量的等价性门槛。
        """
        payload = list(items)
        if not payload:
            return []
        _require_picklable_by_reference(fn)
        if not self.parallel or len(payload) < self.min_items:
            # 宽度不足或规模不足都计入回退，便于任务详情区分「没并行」与「并行失败」。
            self.serial_fallbacks += 1
            return [fn(item) for item in payload]
        self.submitted += len(payload)
        results = list(self._executor_for_use().map(fn, payload, chunksize=chunksize or self.chunksize))
        self.completed += len(payload)
        return results

    def snapshot(self) -> dict[str, Any]:
        """供任务详情展示的最小运行态快照。"""
        return {
            "kind": self.kind,
            "width": self.width,
            "parallel": self.parallel,
            "submitted": self.submitted,
            "completed": self.completed,
            "serial_fallbacks": self.serial_fallbacks,
            "worker_pids": self._worker_pids(),
        }

    def _worker_pids(self) -> list[int]:
        executor = self._executor
        if executor is None:
            return []
        return sorted(pid for pid in getattr(executor, "_processes", {}) or [])

    def close(self) -> None:
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> WorkPool:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _require_picklable_by_reference(fn: Callable[..., Any]) -> None:
    """``spawn`` 按引用 pickle 任务函数，闭包/``__main__`` 函数在子进程里取不到。

    提前给出明确错误，避免在池内部抛出难以定位的 pickling 异常。
    """
    qualname = getattr(fn, "__qualname__", "")
    if getattr(fn, "__module__", "") in {"__main__", ""} or "<locals>" in qualname:
        raise ValueError(f"工作池任务必须是可导入的模块级函数，收到 {fn!r}")


__all__: Sequence[str] = (
    "MIN_PARALLEL_ITEMS",
    "WorkPool",
    "cpu_budget",
    "share_budget",
)
