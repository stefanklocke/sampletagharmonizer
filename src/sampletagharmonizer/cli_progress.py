from __future__ import annotations

import sys
import time


class ProgressBar:
    def __init__(self, total: int, width: int = 32, success_label: str = "indexed") -> None:
        self.total = max(total, 0)
        self.width = width
        self.success_label = success_label
        self.started_at = time.monotonic()
        self.last_rendered_at = 0.0

    def __call__(self, scanned: int, indexed: int, errors: int) -> None:
        now = time.monotonic()
        if scanned < self.total and now - self.last_rendered_at < 0.2:
            return
        self.render(scanned, indexed, errors)

    def render(self, scanned: int, indexed: int, errors: int) -> None:
        self.last_rendered_at = time.monotonic()
        elapsed = max(self.last_rendered_at - self.started_at, 0.001)
        rate = scanned / elapsed
        percent = scanned / self.total if self.total else 0
        filled = min(self.width, int(self.width * percent)) if self.total else 0
        bar = "#" * filled + "-" * (self.width - filled)
        eta = _format_duration((self.total - scanned) / rate) if rate and self.total else "--:--"
        line = (
            f"\r[{bar}] {percent:6.2%} "
            f"{scanned}/{self.total} scanned | "
            f"{indexed} {self.success_label} | {errors} errors | "
            f"{rate:5.1f}/s | ETA {eta}"
        )
        sys.stderr.write(line)
        sys.stderr.flush()

    def finish(self, scanned: int, indexed: int, errors: int) -> None:
        self.render(scanned, indexed, errors)
        sys.stderr.write("\n")
        sys.stderr.flush()


def _format_duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
