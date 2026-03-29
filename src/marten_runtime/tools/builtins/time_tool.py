from datetime import datetime, timezone


def run_time_tool(payload: dict) -> dict:
    return {
        "timezone": payload.get("timezone", "UTC"),
        "iso_time": datetime.now(timezone.utc).isoformat(),
    }
