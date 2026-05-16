from __future__ import annotations

from .decoder import decode_prefix, looks_like_ni_tag_object
from .models import MsgpackDecodeError, MsgpackDecodeResult

__all__ = [
    "MsgpackDecodeError",
    "MsgpackDecodeResult",
    "decode_prefix",
    "looks_like_ni_tag_object",
]
