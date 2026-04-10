import threading
import time
import unittest

from marten_runtime.runtime.lanes import ConversationLaneManager


class ConversationLaneManagerTests(unittest.TestCase):
    def test_same_lane_acquire_is_fifo_instead_of_rejected(self) -> None:
        manager = ConversationLaneManager()
        started: list[str] = []
        first_started = threading.Event()
        release_first = threading.Event()
        second_finished = threading.Event()

        def first() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-1",
                trace_id="trace-1",
            )
            started.append(lease.run_id)
            first_started.set()
            release_first.wait(timeout=2)
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        def second() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-2",
                trace_id="trace-2",
            )
            started.append(lease.run_id)
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)
            second_finished.set()

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        self.assertTrue(first_started.wait(timeout=2))
        second_thread.start()

        self.assertFalse(second_finished.wait(timeout=0.2))
        stats = manager.stats()
        self.assertEqual(stats["active_lane_count"], 1)
        self.assertEqual(stats["queued_lane_count"], 1)
        self.assertEqual(stats["queued_items_total"], 1)

        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        self.assertEqual(started, ["run-1", "run-2"])

    def test_same_lane_lease_records_queue_wait_observation(self) -> None:
        manager = ConversationLaneManager()
        first_started = threading.Event()
        release_first = threading.Event()
        second_lease = {}

        def first() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-1",
                trace_id="trace-1",
            )
            first_started.set()
            release_first.wait(timeout=2)
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        def second() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-2",
                trace_id="trace-2",
            )
            second_lease["value"] = lease
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        self.assertTrue(first_started.wait(timeout=2))
        second_thread.start()
        time.sleep(0.05)
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)

        lease = second_lease["value"]
        self.assertEqual(lease.queue_depth_at_enqueue, 2)
        self.assertGreaterEqual(lease.queue_wait_ms, 1)
        self.assertTrue(lease.waited_in_lane)

    def test_release_advances_next_waiter_on_same_lane(self) -> None:
        manager = ConversationLaneManager()
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()

        def first() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-1",
                trace_id="trace-1",
            )
            first_started.set()
            release_first.wait(timeout=2)
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        def second() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-2",
                trace_id="trace-2",
            )
            second_started.set()
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        self.assertTrue(first_started.wait(timeout=2))
        second_thread.start()

        self.assertFalse(second_started.wait(timeout=0.2))
        release_first.set()

        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
        self.assertTrue(second_started.is_set())

    def test_different_lanes_can_run_concurrently(self) -> None:
        manager = ConversationLaneManager()
        first_started = threading.Event()
        second_started = threading.Event()
        release_both = threading.Event()

        def left() -> None:
            lease = manager.acquire(
                channel_id="http",
                conversation_id="conv-1",
                run_id="run-1",
                trace_id="trace-1",
            )
            first_started.set()
            release_both.wait(timeout=2)
            manager.release(channel_id="http", conversation_id="conv-1", run_id=lease.run_id)

        def right() -> None:
            lease = manager.acquire(
                channel_id="feishu",
                conversation_id="conv-2",
                run_id="run-2",
                trace_id="trace-2",
            )
            second_started.set()
            release_both.wait(timeout=2)
            manager.release(channel_id="feishu", conversation_id="conv-2", run_id=lease.run_id)

        left_thread = threading.Thread(target=left)
        right_thread = threading.Thread(target=right)
        left_thread.start()
        right_thread.start()

        self.assertTrue(first_started.wait(timeout=2))
        self.assertTrue(second_started.wait(timeout=2))
        stats = manager.stats()
        self.assertEqual(stats["active_lane_count"], 2)
        self.assertEqual(stats["queued_lane_count"], 0)

        release_both.set()
        left_thread.join(timeout=2)
        right_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
