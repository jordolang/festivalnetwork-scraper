"""Save/load scored results so the picker can be reopened without re-scraping."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from pathlib import Path

from .models import Event, ScoreBreakdown, ScoredEvent

_DATE_FIELDS = ("start_date", "end_date")


def save_results(scored: list[ScoredEvent], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "results": [
            {
                "event": dataclasses.asdict(s.event),
                "breakdown": dataclasses.asdict(s.breakdown),
            }
            for s in scored
        ],
    }

    def default(o):
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(f"unserializable {type(o)!r}")

    path.write_text(json.dumps(payload, default=default))
    return path


def load_results(path: str | Path) -> list[ScoredEvent]:
    payload = json.loads(Path(path).read_text())
    out: list[ScoredEvent] = []
    for row in payload["results"]:
        ev_data = dict(row["event"])
        for f in _DATE_FIELDS:
            if ev_data.get(f):
                ev_data[f] = date.fromisoformat(ev_data[f])
        out.append(
            ScoredEvent(
                event=Event(**ev_data),
                breakdown=ScoreBreakdown(**row["breakdown"]),
            )
        )
    return out
