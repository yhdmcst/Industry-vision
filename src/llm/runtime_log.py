"""Drain owned subprocess pipes into bounded rotating files without blocking capture."""

from pathlib import Path
import threading
import tempfile

MAX_LOG_BYTES = 1024 * 1024
LOG_BACKUPS = 3


class RuntimeLog:
    def __init__(self, path: Path, max_bytes=MAX_LOG_BYTES, backups=LOG_BACKUPS):
        self.path, self.max_bytes, self.backups = path, max_bytes, backups
        self.lock = threading.Lock()
        self.threads = []
        self.error = ''
        try:
            for index in range(backups+1):
                candidate = path if not index else path.with_name(f'{path.name}.{index}')
                if candidate.is_file() and candidate.stat().st_size > max_bytes:
                    with candidate.open('rb') as handle:
                        handle.seek(-max_bytes, 2); recent = handle.read(max_bytes)
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.log-trim-', delete=False) as handle:
                            temporary = Path(handle.name)
                            handle.write(recent)
                        temporary.replace(candidate)
                    finally:
                        if temporary is not None: temporary.unlink(missing_ok=True)
        except OSError as exc: self.error = str(exc)

    def append(self, data):
        with self.lock:
            # A pipe chunk is capped by attach(), but direct callers are also bounded.
            for offset in range(0, len(data), self.max_bytes):
                part = data[offset:offset + self.max_bytes]
                if self.path.exists() and self.path.stat().st_size + len(part) > self.max_bytes:
                    for index in range(self.backups, 0, -1):
                        source = self.path if index == 1 else self.path.with_name(f'{self.path.name}.{index - 1}')
                        destination = self.path.with_name(f'{self.path.name}.{index}')
                        if source.exists(): source.replace(destination)
                with self.path.open('ab') as handle: handle.write(part)

    def attach(self, process):
        def drain():
            try:
                while True:
                    data = process.stdout.read(4096)
                    if not data: break
                    try: self.append(data)
                    except OSError as exc: self.error = str(exc)
                    # Continue draining on disk failure: never deadlock an owned process.
            finally:
                process.stdout.close()
        thread = threading.Thread(target=drain, name='model-log', daemon=True)
        self.threads = [previous for previous in self.threads if previous.is_alive()]
        self.threads.append(thread)
        thread.start()

    def finish(self):
        for thread in self.threads:
            thread.join(timeout=3)

    def tail(self, limit=16384):
        with self.lock:
            if not self.path.is_file(): return ''
            with self.path.open('rb') as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - limit))
                return handle.read(limit).decode('utf-8', errors='replace')
