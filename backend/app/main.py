"""
FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.routes import compare

app = FastAPI(
    title="Attendance Comparison API",
    description="Compares attendance records against client work logs and flags discrepancies.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compare.router)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
