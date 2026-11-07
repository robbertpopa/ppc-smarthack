import logging
from collections.abc import Iterator
from pathlib import Path
from threading import Lock

from src.common.contract import ActionEvent

logger = logging.getLogger(__name__)

BLOCK = 8192


def _parse(line: bytes | str) -> ActionEvent | None:
    if not line.strip():
        return None
    try:
        return ActionEvent.model_validate_json(line)
    except ValueError:
        logger.warning("skipping an unreadable action log line")
        return None


class ActionLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._end_torn_line()

    def _end_torn_line(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb+") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                f.write(b"\n")

    def append(self, event: ActionEvent) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read(self, limit: int = 100) -> list[ActionEvent]:
        if limit <= 0 or not self.path.exists():
            return []
        with self.path.open("rb") as f:
            pos = f.seek(0, 2)
            data = b""
            while pos > 0 and data.count(b"\n") <= limit:
                step = min(BLOCK, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
        lines = data.splitlines()
        if pos > 0:
            lines = lines[1:]
        events = (_parse(line) for line in lines[-limit:])
        return [e for e in events if e is not None]

    def read_all(self) -> Iterator[ActionEvent]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                event = _parse(line)
                if event is not None:
                    yield event


def open_log(uri: str) -> ActionLog:
    if "://" in uri:
        raise NotImplementedError(f"only local paths are supported for the action log, got {uri}")
    return ActionLog(uri)
