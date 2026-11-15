# -*- coding: utf-8 -*-
"""有预算的并发执行器。

为什么不用 ThreadPoolExecutor：
  * 它的 `shutdown(wait=True)` 会等所有线程结束——只要有一个线程卡在
    `getaddrinfo`（DNS 卡住时不受 socket timeout 约束），整个进程就僵死，
    实测能挂 9 小时不返回。
  * 它用非守护线程，解释器退出时还会 join，同样被拖住。

这里改成：守护线程 + Queue + 截止时间。到点就带着「已完成的部分」返回，
没跑完的由调用方标记为超时。坏源只影响自己，不影响整次检索。
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple


class Deadline:
    def __init__(self, budget: Optional[float]):
        self.started = time.monotonic()
        self.budget = budget
        self.deadline = None if budget is None else self.started + budget

    @property
    def remaining(self) -> Optional[float]:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def expired(self) -> bool:
        return self.deadline is not None and time.monotonic() >= self.deadline

    def clamp(self, timeout: float) -> float:
        """把单个请求超时压进剩余预算，避免最后一个请求拖爆总预算。"""
        rem = self.remaining
        if rem is None:
            return timeout
        return max(1.0, min(timeout, rem))


def run_with_deadline(
    func: Callable[[Any], Any],
    items: List[Any],
    budget: Optional[float] = None,
    on_done: Optional[Callable[[int, Any, Optional[BaseException]], None]] = None,
    deadline: Optional[Deadline] = None,
    checkpoint_after: float = 0.0,
    on_checkpoint: Optional[Callable[[Dict[int, Any]], None]] = None,
) -> Tuple[Dict[int, Any], List[int], List[BaseException]]:
    """并发跑 func(item)，到点即返回。

    checkpoint_after: 跑了多少秒后先交一次「已完成的部分」，然后继续等剩下的。
                      用于「先出结果、慢源后补」的界面体验。

    returns: (结果字典 {index: value}, 未完成的 index 列表, 异常列表)
    """
    dl = deadline or Deadline(budget)
    q: "queue.Queue[Tuple[int, Any, Optional[BaseException]]]" = queue.Queue()
    results: Dict[int, Any] = {}
    errors: List[BaseException] = []
    started = time.monotonic()
    checkpoint_fired = checkpoint_after <= 0

    def worker(idx: int, item: Any) -> None:
        try:
            q.put((idx, func(item), None))
        except BaseException as exc:  # noqa: BLE001  # 线程里不能让它静默死
            q.put((idx, None, exc))

    for i, item in enumerate(items):
        t = threading.Thread(target=worker, args=(i, item), name=f"cmf-{i}", daemon=True)
        t.start()

    pending = len(items)
    while pending > 0:
        rem = dl.remaining
        if rem is not None and rem <= 0:
            break
        wait = rem
        if not checkpoint_fired:
            cp_left = max(0.0, checkpoint_after - (time.monotonic() - started))
            wait = cp_left if wait is None else min(wait, cp_left)
        try:
            idx, value, exc = q.get(timeout=wait if wait is not None else None)
        except queue.Empty:
            if not checkpoint_fired:
                checkpoint_fired = True
                if on_checkpoint:
                    on_checkpoint(dict(results))
            continue
        pending -= 1
        if exc is not None:
            errors.append(exc)
            results[idx] = None
        else:
            results[idx] = value
        if on_done:
            on_done(idx, value, exc)

    if not checkpoint_fired and on_checkpoint and results:
        checkpoint_fired = True
        on_checkpoint(dict(results))

    unfinished = [i for i in range(len(items)) if i not in results]
    return results, unfinished, errors
