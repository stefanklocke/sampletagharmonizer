from __future__ import annotations

from fastapi import FastAPI

from sampletagharmonizer.db.session import healthcheck

app = FastAPI(title="Sample Tag Harmonizer")


@app.get("/health")
def health() -> dict[str, str]:
    healthcheck()
    return {"status": "ok"}
