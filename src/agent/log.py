from pathlib import Path
from threading import Lock

from src.common.contract import ActionEvent


class ActionLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, event: ActionEvent) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read(self, limit: int = 100) -> list[ActionEvent]:
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        return [ActionEvent.model_validate_json(line) for line in lines[-limit:] if line]


def open_log(uri: str) -> ActionLog:
    if "://" in uri:
        raise NotImplementedError(f"only local paths are supported for the action log, got {uri}")
    return ActionLog(uri)
