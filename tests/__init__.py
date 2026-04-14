import atexit
from tests.support.event_loop import close_idle_event_loop


atexit.register(close_idle_event_loop)
