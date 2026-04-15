from __future__ import annotations

import asyncio
import sys


_KNOWN_GLOBAL_LOOP_SLOTS = (("lark_oapi.ws.client", "loop"),)


def close_idle_event_loops() -> None:
    _close_policy_loop()
    _close_known_global_loops()


def _close_policy_loop() -> None:
    policy = asyncio.get_event_loop_policy()
    local = getattr(policy, "_local", None)
    loop = getattr(local, "_loop", None)
    if not isinstance(loop, asyncio.AbstractEventLoop):
        return
    if loop.is_running() or loop.is_closed():
        return
    loop.close()
    try:
        asyncio.set_event_loop(None)
    except RuntimeError:
        pass


def _close_known_global_loops() -> None:
    for module_name, attribute_name in _KNOWN_GLOBAL_LOOP_SLOTS:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        loop = getattr(module, attribute_name, None)
        if not isinstance(loop, asyncio.AbstractEventLoop):
            continue
        if loop.is_running() or loop.is_closed():
            continue
        loop.close()
        try:
            setattr(module, attribute_name, None)
        except Exception:
            pass
