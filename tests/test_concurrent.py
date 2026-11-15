# -*- coding: utf-8 -*-
"""并发执行器测试：预算到点必须返回，不能被卡住的线程拖死。"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cmf.concurrent import Deadline, run_with_deadline  # noqa: E402


def _slow(x, seconds=5.0):
    time.sleep(seconds)
    return x * 2


class TestDeadline(unittest.TestCase):
    def test_clamp(self):
        dl = Deadline(1.0)
        self.assertLessEqual(dl.clamp(30.0), 1.0)
        dl2 = Deadline(None)
        self.assertEqual(dl2.clamp(30.0), 30.0)
        self.assertFalse(dl2.expired())

    def test_expired(self):
        dl = Deadline(0.05)
        time.sleep(0.12)
        self.assertTrue(dl.expired())
        self.assertEqual(dl.remaining, 0.0)


class TestRunWithDeadline(unittest.TestCase):
    def test_returns_completed_and_marks_rest(self):
        t0 = time.monotonic()
        results, unfinished, errors = run_with_deadline(
            lambda item: _slow(item, 5.0 if item == "slow" else 0.01),
            ["fast", "slow"],
            budget=0.6,
        )
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 3.0, "预算到点必须返回，不能等 sleep(5)")
        self.assertEqual(len(results), 1)
        self.assertIn(0, results)  # 快任务拿到了
        self.assertEqual(unfinished, [1])  # 慢任务被标记为未完成
        self.assertEqual(errors, [])

    def test_collects_exceptions(self):
        def boom(_):
            raise ValueError("bad source")

        results, unfinished, errors = run_with_deadline(boom, [1], budget=2.0)
        self.assertEqual(unfinished, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)

    def test_no_budget_runs_all(self):
        results, unfinished, errors = run_with_deadline(lambda i: i + 1, list(range(20)), budget=None)
        self.assertEqual(unfinished, [])
        self.assertEqual(sorted(results.values()), list(range(1, 21)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
