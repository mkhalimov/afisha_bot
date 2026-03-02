import re
from datetime import date, datetime, time
from typing import Optional

DATE_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{4})\s*$")
TIME_RE = re.compile(r"^\s*(\d{2}):(\d{2})\s*$")

CAPTION_LIMIT = 1024


def parse_date_ru(s: str) -> Optional[date]:
    m = DATE_RE.match(s)
    if not m:
        return None
    dd, mm, yyyy = map(int, m.groups())
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


def parse_time_hhmm(s: str) -> Optional[time]:
    m = TIME_RE.match(s)
    if not m:
        return None
    hh, mi = map(int, m.groups())
    try:
        return time(hh, mi)
    except ValueError:
        return None


def format_preview(data: dict) -> str:
    lines = []
    if data.get("category"):
        lines.append(f"АФИША | {data['category']}")
    if data.get("title"):
        lines.append("")
        lines.append(data["title"])
    if data.get("event_date") and data.get("time_start") and data.get("time_end"):
        d = datetime.strptime(data["event_date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        lines.append("")
        lines.append(f"{data['time_start']} - {data['time_end']}, {d}")
    if data.get("location"):
        lines.append(data["location"])
    if data.get("description"):
        lines.append("")
        lines.append(data["description"])
    if data.get("organizer"):
        lines.append("")
        lines.append(f"Организатор: {data['organizer']}")
    return "\n".join(lines).strip()


def format_preview_safe(data: dict) -> str:
    """Same as format_preview but truncated to Telegram caption limit (1024 chars)."""
    text = format_preview(data)
    if len(text) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - 1] + "…"
    return text
