import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def run_time_tool(payload: dict) -> dict:
    requested_timezone = _resolve_timezone(payload)
    current_time = datetime.now(timezone.utc).astimezone(requested_timezone)
    timezone_label = _resolve_timezone_label(payload)
    return {
        "timezone": timezone_label,
        "iso_time": current_time.isoformat(),
    }


def _resolve_timezone_label(payload: dict) -> str:
    for key in ("timezone", "tz", "utc_offset"):
        value = str(payload.get(key, "")).strip()
        if value:
            return value
    return _detect_local_timezone_label()


def _detect_local_timezone_label() -> str:
    env_timezone = str(os.environ.get("TZ", "")).strip()
    if env_timezone:
        return env_timezone
    timezone_file = Path("/etc/timezone")
    if timezone_file.exists():
        try:
            file_timezone = timezone_file.read_text(encoding="utf-8").strip()
        except OSError:
            file_timezone = ""
        if file_timezone:
            return file_timezone
    localtime = Path("/etc/localtime")
    if localtime.exists() and localtime.is_symlink():
        zoneinfo_path = str(localtime.resolve())
        marker = "zoneinfo/"
        if marker in zoneinfo_path:
            return zoneinfo_path.split(marker, 1)[1]
    local_datetime = datetime.now().astimezone()
    if local_datetime.tzinfo is timezone.utc:
        return "UTC"
    offset = local_datetime.utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    absolute_seconds = abs(total_seconds)
    hours, remainder = divmod(absolute_seconds, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"
def _resolve_timezone(payload: dict):
    label = _resolve_timezone_label(payload)
    if label.upper() == "UTC":
        return timezone.utc
    if label.startswith("+") or label.startswith("-"):
        sign = 1 if label[0] == "+" else -1
        hours_text, minutes_text = label[1:].split(":", 1)
        offset = timedelta(hours=int(hours_text), minutes=int(minutes_text))
        return timezone(sign * offset)
    return ZoneInfo(label)
