"""Append-only local evidence, scoped to a monitoring session."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator
from contextlib import closing, contextmanager


class EvidenceStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL,
                    kind TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session ON events(session, id);
                CREATE INDEX IF NOT EXISTS events_nonframe ON events(session, id) WHERE kind != 'frame';
                CREATE INDEX IF NOT EXISTS events_kind ON events(session, kind, id);
                CREATE INDEX IF NOT EXISTS events_incident ON events(session, kind, json_extract(payload, '$.incident_id'), id)
                    WHERE json_valid(payload);
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, session: str, kind: str, created: float, payload: dict[str, Any], *,
               connection: sqlite3.Connection | None = None) -> int:
        return self.append_many(session, [(kind, created, payload)], connection=connection)[0]

    def append_many(self, session: str, events: list[tuple[str, float, dict[str, Any]]], *,
                    connection: sqlite3.Connection | None = None) -> list[int]:
        """Publish related evidence together, or leave the journal unchanged."""
        encoded = [(kind, created, json.dumps(payload, ensure_ascii=False, allow_nan=False))
                   for kind, created, payload in events]
        def insert(db):
            ids = []
            for kind, created, payload in encoded:
                cursor = db.execute(
                    "INSERT INTO events(session,kind,created,payload) VALUES (?,?,?,?)",
                    (session, kind, created, payload),
                )
                ids.append(int(cursor.lastrowid))
            return ids
        if connection is not None:
            return insert(connection)
        with self.connect() as db:
            return insert(db)

    def events(self, session: str, limit: int = 1000, kind: str | None = None) -> list[dict[str, Any]]:
        filter_sql = " AND kind=?" if kind is not None else ""
        parameters = (session, kind) if kind is not None else (session,)
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,kind,created,payload FROM events WHERE session=?" + filter_sql + " ORDER BY id DESC LIMIT ?",
                (*parameters, max(1, min(limit, 10000))),
            ).fetchall()
        return [{"id": row[0], "kind": row[1], "created": row[2],
                 "payload": json.loads(row[3])} for row in reversed(rows)]

    def count(self, session: str) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM events WHERE session=?", (session,)).fetchone()[0]

    def all_events(self, session: str, kind: str | None = None, incident_id: int | None = None):
        conditions, parameters = ['session=?'], [session]
        if kind is not None: conditions.append('kind=?'); parameters.append(kind)
        if incident_id is not None:
            conditions.append("json_valid(payload) AND json_extract(payload, '$.incident_id')=?")
            parameters.append(incident_id)
        with self.connect() as db:
            rows = db.execute('SELECT id,kind,created,payload FROM events WHERE ' + ' AND '.join(conditions) + ' ORDER BY id', parameters).fetchall()
        return [{'id': r[0], 'kind': r[1], 'created': r[2], 'payload': json.loads(r[3])} for r in rows]

    def export_session(self, session, metadata):
        """Stream one read snapshot without holding capture's lock or buffering images."""
        with self.connect() as db:
            db.execute('BEGIN')
            count = db.execute('SELECT COUNT(*) FROM events WHERE session=?', (session,)).fetchone()[0]
            header = {**metadata, 'schema_version': 1, 'session': session, 'total_events': count,
                      'event_limit': None, 'truncated': False}
            yield (json.dumps(header, ensure_ascii=False, allow_nan=False)[:-1] + ',"events":[').encode()
            first = True
            for row in db.execute('SELECT id,kind,created,payload FROM events WHERE session=? ORDER BY id', (session,)):
                event = {'id': row[0], 'kind': row[1], 'created': row[2], 'payload': json.loads(row[3])}
                yield (('' if first else ',') + json.dumps(event, ensure_ascii=False, allow_nan=False)).encode()
                first = False
            yield b']}'

    def incident_page(self, session, *, limit=50, before=None, status='all', search='', frame=None, baseline_generation=None):
        """Keyset pagination and latest assessment in one consistent SQLite snapshot."""
        predicates, parameters = ['e.session=?', "e.kind='incident'"], [session]
        if before is not None: predicates.append('e.id<?'); parameters.append(before)
        if frame is not None:
            predicates.append("(json_extract(e.payload,'$.frame')=? OR EXISTS (SELECT 1 FROM events u WHERE u.session=e.session AND u.kind='incident_updated' AND json_extract(u.payload,'$.incident_id')=e.id AND json_extract(u.payload,'$.frame')=?))")
            parameters.extend([frame, frame])
        if baseline_generation is not None:
            predicates.append("json_extract(e.payload,'$.baseline_generation')=?")
            parameters.append(baseline_generation)
        latest = "(SELECT a.id FROM events a WHERE a.session=e.session AND a.kind='incident_assessment' AND json_valid(a.payload) AND json_extract(a.payload,'$.incident_id')=e.id ORDER BY a.id DESC LIMIT 1)"
        if status != 'all': predicates.append(f'{latest} IS ' + ('NULL' if status == 'pending' else 'NOT NULL'))
        if search:
            label = "CASE json_extract(e.payload,'$.rule_report.drift_type') WHEN 'none' THEN '未触发规则' WHEN 'optical' THEN '光学变化' WHEN 'illumination' THEN '光照变化' WHEN 'mechanical' THEN '位置／稳定性变化' WHEN 'product' THEN '检测结果变化' ELSE '原因待核验' END"
            predicates.append(f"(CAST(e.id AS TEXT) LIKE ? ESCAPE '\\' OR json_extract(e.payload,'$.rule_report.drift_type') LIKE ? ESCAPE '\\' OR {label} LIKE ? ESCAPE '\\')")
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            parameters.extend([f'%{escaped}%'] * 3)
        # Never retrieve frozen image payloads for a queue of summaries.
        fields = ['frame', 'source', 'injected', 'baseline_generation', 'trigger']
        extracts = ','.join(f"json_extract(e.payload,'$.{field}')" for field in fields)
        with self.connect() as db:
            rows = db.execute(f"SELECT e.id,e.created,{extracts},json_extract(e.payload,'$.rule_report.drift_type'),(SELECT payload FROM events WHERE id={latest}) FROM events e WHERE " + ' AND '.join(predicates) + ' ORDER BY e.id DESC LIMIT ?', (*parameters, limit + 1)).fetchall()
        items = [{'id': r[0], 'created': r[1], **dict(zip(fields, r[2:7])), 'drift_type': r[7],
                  'assessment': json.loads(r[8]) if r[8] else None} for r in rows[:limit]]
        return {'items': items, 'next_before': items[-1]['id'] if len(rows) > limit else None}

    def revision(self, session: str) -> int:
        with self.connect() as db:
            return db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE session=? AND kind != 'frame'", (session,)).fetchone()[0]

    def backup(self, destination: Path):
        """Snapshot committed WAL evidence; no copy of a live database file."""
        import time
        destination = Path(destination)
        if destination.exists(): raise ValueError('备份目标已存在，请选择新路径')
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        deadline = time.monotonic() + 60
        def progress(*_):
            if time.monotonic() > deadline: raise RuntimeError('证据备份超时，请稍后重试')
        try:
            with self.connect() as source, closing(sqlite3.connect(destination)) as target:
                source.backup(target, pages=128, progress=progress, sleep=.01)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('证据备份完整性检查失败')
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def storage_info(self):
        with self.connect() as db:
            events, sessions = db.execute('SELECT COUNT(*),COUNT(DISTINCT session) FROM events').fetchone()
        try: wal_bytes = self.path.with_name(self.path.name + '-wal').stat().st_size
        except FileNotFoundError: wal_bytes = 0
        return {'database_bytes': self.path.stat().st_size,
                'wal_bytes': wal_bytes,
                'events': events, 'sessions': sessions,
                'scope': '会话图像、指标、事件、人工记录和模型操作记录；不含外部数据集、模型文件及部署配置'}

    def event(self, session: str, event_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT id,kind,created,payload FROM events WHERE session=? AND id=?",
                             (session, event_id)).fetchone()
        if row is None:
            raise ValueError("Evidence event does not exist in this session")
        return {"id": row[0], "kind": row[1], "created": row[2], "payload": json.loads(row[3])}

    def sessions(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT session, MIN(created), MAX(created), COUNT(*) FROM events "
                "GROUP BY session ORDER BY MAX(created) DESC,session LIMIT ? OFFSET ?",
                (max(1, min(limit, 100)), offset),
            ).fetchall()
        return [{"session": row[0], "started": row[1], "last_event": row[2], "count": row[3]} for row in rows]


def restore_evidence(source: Path, destination: Path):
    """Validate a backup and publish a new DB. Never replace a running workspace."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file(): raise ValueError('备份文件不存在')
    if destination.exists(): raise ValueError('恢复目标已存在；请选择新数据库路径')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as backup:
        if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('备份数据库完整性检查失败')
        columns = {row[1] for row in backup.execute('PRAGMA table_info(events)')}
        if columns != {'id', 'session', 'kind', 'created', 'payload'}:
            raise ValueError('不是受支持的会话证据备份')
        def invalid_constant(value): raise ValueError(f'证据含非法数值：{value}')
        for (payload,) in backup.execute('SELECT payload FROM events'):
            if not isinstance(json.loads(payload, parse_constant=invalid_constant), dict):
                raise ValueError('备份证据格式无效')
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Reserve exclusively: another process cannot make us overwrite its database.
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(destination)) as target:
                backup.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('恢复数据库完整性检查失败')
                count = target.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return {'path': str(destination), 'events': count, 'source_preserved': True}
