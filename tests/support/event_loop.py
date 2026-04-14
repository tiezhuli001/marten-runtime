import asyncio


def close_idle_event_loop() -> None:
    policy = asyncio.get_event_loop_policy()
    try:
        loop = policy.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running() or loop.is_closed():
        return
    loop.close()
    try:
        asyncio.set_event_loop(None)
    except RuntimeError:
        pass
