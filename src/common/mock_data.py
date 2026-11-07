from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

MOCK_DIR = Path(__file__).parent / "mocks"


def load_mock(name: str, model: type[M]) -> M:
    return model.model_validate_json((MOCK_DIR / f"{name}.json").read_text())
