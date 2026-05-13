import asyncio
import sys
import types
import unittest

from marten_runtime.runtime.event_loop_cleanup import close_idle_event_loops


class ClosingLoop(asyncio.AbstractEventLoop):
    def __init__(self) -> None:
        self.closed = False

    def is_running(self):
        return False

    def is_closed(self):
        return False

    def close(self):
        raise ValueError("I/O operation on closed kqueue object")


class EventLoopCleanupTests(unittest.TestCase):
    def test_close_idle_event_loops_swallows_known_global_loop_close_errors(self) -> None:
        module_name = "lark_oapi.ws.client"
        old_module = sys.modules.get(module_name)
        fake_module = types.SimpleNamespace(loop=ClosingLoop())
        sys.modules[module_name] = fake_module
        try:
            close_idle_event_loops()
        finally:
            if old_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = old_module

        self.assertIsNone(fake_module.loop)


if __name__ == "__main__":
    unittest.main()
