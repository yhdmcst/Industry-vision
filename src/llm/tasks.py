"""Durable operation records, separate from immutable inspection evidence."""

import copy
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

ACTIVE = {'running', 'cancelling'}


class ModelTasks:
    def __init__(self, database):
        self.database = database
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS model_tasks (id TEXT PRIMARY KEY, created REAL NOT NULL, record TEXT NOT NULL)')
            rows = db.execute('SELECT record FROM model_tasks ORDER BY created DESC LIMIT 20').fetchall()
            self.records = [json.loads(row[0]) for row in rows]
            for record in self.records:
                if record['status'] in ACTIVE:
                    record.update(status='interrupted', finished=time.time(),
                                  stage='工作台已重启', error='上次操作中断；检查当前状态后可重新执行，不自动重发。')
                    self._write(db, record)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=2)
        try:
            with db: yield db
        finally: db.close()

    @staticmethod
    def _write(db, record):
        db.execute('INSERT INTO model_tasks(id,created,record) VALUES (?,?,?) '
                   'ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                   (record['id'], record['created'], json.dumps(record, ensure_ascii=False, allow_nan=False)))

    def begin(self, action, target):
        record = {'id': uuid.uuid4().hex, 'action': action, 'target': target,
                  'status': 'running', 'stage': '操作已开始', 'created': time.time(),
                  'finished': None, 'error': ''}
        with self.connect() as db: self._write(db, record)
        self.records = [record, *self.records[:19]]
        return record['id']

    def update(self, task_id, **values):
        record = next(record for record in self.records if record['id'] == task_id)
        updated = {**record, **values}
        with self.connect() as db: self._write(db, updated)
        record.update(values)

    def snapshot(self):
        return copy.deepcopy(self.records)
