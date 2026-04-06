from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers.ai import router as ai_router
from .routers.backtest import router as backtest_router
from .routers.module import router as module_router
from .routers.strategy import router as strategy_router
from .services.storage import ensure_directories


ensure_directories()

app = FastAPI(
    title="Freqtrade Strategy Studio API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(module_router, prefix="/api/module", tags=["module"])
app.include_router(strategy_router, prefix="/api/strategy", tags=["strategy"])
app.include_router(backtest_router, prefix="/api/backtest", tags=["backtest"])
app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
