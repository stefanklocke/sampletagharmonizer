from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class MsgpackDecodeError(ValueError):
    pass


@dataclass(frozen=True)
class MsgpackDecodeResult:
    value: Any
    consumed: int
