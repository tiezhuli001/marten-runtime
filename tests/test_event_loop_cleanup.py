import asyncio
import sys
import types
import unittest

from marten_runtime.runtime.event_loop_cleanup import close_idle_event_loops


class EventLoopCleanupTests(unittest.TestCase):
    def test_close_idle_event_loops_closes_lark_client_global_loop(self) -> None:
        module_name = "lark_oapi.ws.client"
        original_module = sys.modules.get(module_name)
        fake_module = types.ModuleType(module_name)
        loop = asyncio.new_event_loop()
        fake_module.loop = loop
        sys.modules[module_name] = fake_module
        try:
            self.assertFalse(loop.is_closed())

            close_idle_event_loops()

            self.assertTrue(loop.is_closed())
            self.assertIsNone(getattr(fake_module, "loop", None))
        finally:
            if original_module is not None:
                sys.modules[module_name] = original_module
            else:
                sys.modules.pop(module_name, None)
            if not loop.is_closed():
                loop.close()


if __name__ == "__main__":
    unittest.main()
