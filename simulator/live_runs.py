"""Durable phase-specific runs. A reset invalidates callbacks, not historical evidence."""
import json
import sqlite3
import threading
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class LiveRuns:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.epoch = 0
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS live_runs (id TEXT PRIMARY KEY, scope_id TEXT, phase TEXT, status TEXT, started_at TEXT, completed_at TEXT, payload TEXT)')
            db.execute("UPDATE live_runs SET status='interrupted' WHERE status='running'")

    def reset(self):
        with self.lock:
            self.epoch += 1
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE live_runs SET status='superseded', completed_at=? WHERE status='running'", (now(),))

    def get(self, run_id):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM live_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result.update(json.loads(result.pop('payload') or '{}'))
        return result

    def start(self, run_id, scope_id, phase, work, complete=None):
        with self.lock, sqlite3.connect(self.path) as db:
            epoch = self.epoch
            if db.execute('SELECT 1 FROM live_runs WHERE id=?', (run_id,)).fetchone():
                return False
            db.execute('INSERT INTO live_runs VALUES (?,?,?, ?,?,NULL,?)', (run_id, scope_id, phase, 'running', now(), '{}'))
        def execute():
            try:
                payload = work()
                status = 'ready' if payload.get('ok') else 'unavailable'
            except Exception as error:
                payload = {'ok': False, 'error': f'Live analysis failed ({type(error).__name__}). Retry the live review.'}
                status = 'unavailable'
            with self.lock:
                if epoch != self.epoch:
                    return
                with sqlite3.connect(self.path) as db:
                    db.execute('UPDATE live_runs SET status=?,completed_at=?,payload=? WHERE id=?', (status, now(), json.dumps(payload), run_id))
                if complete:
                    complete(payload)
        threading.Thread(target=execute, daemon=True, name=f'live-{phase}').start()
        return True

    @staticmethod
    def public(run):
        if not run:
            return None
        return {k:v for k,v in run.items() if k not in {'raw_response', 'usage', 'tool_results'}}
