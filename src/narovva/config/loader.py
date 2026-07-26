"""Load channel configs from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schema import ChannelConfig


def load_channel(path: str | Path) -> ChannelConfig:
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    raw.setdefault("id", path.stem)
    return ChannelConfig.model_validate(raw)


def load_all_channels(directory: str | Path = "config/channels") -> list[ChannelConfig]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    channels = [
        load_channel(p) for p in sorted(directory.glob("*.yaml")) if p.is_file()
    ]
    ids = [c.id for c in channels]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate channel id(s) across {directory}: {sorted(dupes)}")
    return channels
