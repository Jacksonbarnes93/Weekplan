"""
Student Scheduler API
─────────────────────
FastAPI application entry point.

Run with:
    uvicorn main:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.api import schedule_router, canvas_router

app = FastAPI(
    title="Student Scheduler API",
    description=(
        "Backend for the student productivity calendar app. "
        "Integrates with Canvas LMS and generates optimized weekly schedules."
    ),
    version="1.0.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Flutter web needs this; for mobile-only you can tighten the origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten this to your Flutter web origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(schedule_router)
app.include_router(canvas_router)


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "message": "Student Scheduler API is running."}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
