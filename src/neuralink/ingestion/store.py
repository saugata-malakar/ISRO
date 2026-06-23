"""Encrypted SQLite fault-history store (README §1.3, §8 ingestion).

Each event's full JSON payload is encrypted with AES-256-GCM (AAD bound to the
row's ``event_id`` so ciphertext can't be transplanted between rows). A few
non-sensitive columns (device, type, time, score) stay in plaintext purely as
query indexes — the operational payload (raw syslog, metrics) is encrypted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from neuralink.config import get_settings
from neuralink.schemas import NetworkEvent
from neuralink.security import crypto

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    sim_time      REAL NOT NULL,
    source_device TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    severity      TEXT NOT NULL,
    anomaly_score REAL,
    blob          BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_device ON events(source_device);
CREATE INDEX IF NOT EXISTS idx_events_type   ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time   ON events(sim_time);
"""


class EventStore:
    """Thin encrypted-at-rest persistence layer for NetworkEvents."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_settings().db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ #
    def add_event(self, event: NetworkEvent) -> None:
        blob = crypto.encrypt_str(event.model_dump_json(), aad=event.event_id.encode())
        self.conn.execute(
            "INSERT OR REPLACE INTO events "
            "(event_id, ts, sim_time, source_device, event_type, severity, anomaly_score, blob) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.timestamp,
                event.sim_time,
                event.source_device,
                event.event_type.value,
                event.severity_raw.value,
                event.anomaly_score,
                blob,
            ),
        )
        self.conn.commit()

    def add_many(self, events: list[NetworkEvent]) -> int:
        for ev in events:
            self.add_event(ev)
        return len(events)

    # ------------------------------------------------------------------ #
    def _decode(self, row: sqlite3.Row) -> NetworkEvent:
        raw = crypto.decrypt_str(row["blob"], aad=row["event_id"].encode())
        return NetworkEvent.model_validate_json(raw)

    def get_event(self, event_id: str) -> NetworkEvent | None:
        cur = self.conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,))
        row = cur.fetchone()
        return self._decode(row) if row else None

    def count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    def all_events(self, limit: int | None = None) -> list[NetworkEvent]:
        q = "SELECT * FROM events ORDER BY sim_time, ts"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [self._decode(r) for r in self.conn.execute(q).fetchall()]

    def recent(self, n: int = 20) -> list[NetworkEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events ORDER BY sim_time DESC, ts DESC LIMIT ?", (n,)
        ).fetchall()
        return [self._decode(r) for r in rows][::-1]

    def by_device(self, device: str) -> list[NetworkEvent]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE source_device=? ORDER BY sim_time", (device,)
        ).fetchall()
        return [self._decode(r) for r in rows]

    def metrics_dataframe(self) -> pd.DataFrame:
        """Flatten all events into a metrics DataFrame (used by detection training)."""
        rows = []
        for ev in self.all_events():
            m = ev.metrics
            rows.append(
                {
                    "event_id": ev.event_id,
                    "device": ev.source_device,
                    "sim_time": ev.sim_time,
                    "event_type": ev.event_type.value,
                    "cpu_pct": m.cpu_pct,
                    "mem_pct": m.mem_pct,
                    "temp_c": m.temp_c,
                    "if_errors": m.if_in_errors + m.if_out_errors,
                    "bgp_down": max(0, m.bgp_peers_total - m.bgp_peers_up),
                    "link_down": 0 if m.link_up else 1,
                    "throughput_mbps": m.throughput_mbps,
                }
            )
        return pd.DataFrame(rows)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
