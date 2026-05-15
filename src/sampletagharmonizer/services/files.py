from __future__ import annotations

from pathlib import Path
from typing import Iterable


def iter_wav_files(root: Path) -> Iterable[Path]:
    yield from root.rglob("*.wav")
