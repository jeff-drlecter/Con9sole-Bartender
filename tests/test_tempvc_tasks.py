from __future__ import annotations

import unittest

from utils import (
    cancel_all_delete_tasks,
    cancel_delete_task,
    clear_delete_task,
    set_delete_task,
)


class FakeTask:
    def __init__(self) -> None:
        self.cancelled = False

    def done(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True


class TempVCTaskRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        cancel_all_delete_tasks()

    def test_completed_task_can_clear_itself_without_cancellation(self) -> None:
        task = FakeTask()
        set_delete_task(123, task)  # type: ignore[arg-type]

        clear_delete_task(123, task)  # type: ignore[arg-type]
        cancel_delete_task(123)

        self.assertFalse(task.cancelled)

    def test_old_task_cannot_clear_newer_replacement(self) -> None:
        old_task = FakeTask()
        new_task = FakeTask()
        set_delete_task(123, old_task)  # type: ignore[arg-type]
        set_delete_task(123, new_task)  # type: ignore[arg-type]

        clear_delete_task(123, old_task)  # type: ignore[arg-type]
        cancel_delete_task(123)

        self.assertTrue(old_task.cancelled)
        self.assertTrue(new_task.cancelled)


if __name__ == "__main__":
    unittest.main()
