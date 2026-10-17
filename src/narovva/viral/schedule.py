"""When a viral post is due: peak-hour slots in the audience's time zone."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..config.schema import ViralConfig


def _slot_times(cfg: ViralConfig, day_start: datetime) -> list[datetime]:
    out = []
    for s in cfg.slots:
        hh, mm = (int(x) for x in s.split(":"))
        out.append(day_start.replace(hour=hh, minute=mm))
    return out


def local_day_start(cfg: ViralConfig, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(cfg.timezone))
    return datetime.combine(local.date(), time(0, 0), tzinfo=local.tzinfo)


def slot_status(cfg: ViralConfig, now: datetime, posted_today: int) -> tuple[bool, str]:
    """(due, why). Due while inside a slot's window and today's viral posts are
    fewer than the slots started so far -- so a slot missed (nothing fresh, a
    dropped scheduler run) is made up in the next slot's window."""
    day = local_day_start(cfg, now)
    started = [t for t in _slot_times(cfg, day) if t <= now.astimezone(day.tzinfo)]
    if not started:
        return False, f"before today's first slot ({cfg.slots[0]} {cfg.timezone})"
    latest = started[-1]
    window_end = latest + timedelta(minutes=cfg.slot_window_minutes)
    if now.astimezone(day.tzinfo) >= window_end:
        return False, f"outside peak windows (last slot {latest:%H:%M} {cfg.timezone} ended {window_end:%H:%M})"
    if posted_today >= len(started):
        return False, f"slot {latest:%H:%M} already filled ({posted_today}/{len(cfg.slots)} today)"
    return True, f"slot {latest:%H:%M} {cfg.timezone} ({posted_today}/{len(cfg.slots)} posted today)"
