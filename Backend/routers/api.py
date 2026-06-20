"""
API Routers
───────────
/schedule   → Generate and retrieve schedules
/canvas     → Canvas LMS integration
"""

from fastapi import APIRouter, HTTPException, status
from models.schemas import (
    ScheduleRequest, ScheduleResponse,
    CanvasTokenRequest, CanvasAssignment,
)
from services.scheduler import StudentScheduler
from services.canvas_service import CanvasService

# ─────────────────────────────────────────────
# Schedule Router
# ─────────────────────────────────────────────

schedule_router = APIRouter(prefix="/schedule", tags=["Schedule"])
scheduler = StudentScheduler()


@schedule_router.post(
    "/generate",
    response_model=ScheduleResponse,
    summary="Generate a weekly schedule",
    description=(
        "Takes the student's full week configuration (available windows, "
        "fixed events, tasks + time estimates, and preferences) and returns "
        "an optimized day-by-day schedule."
    ),
)
async def generate_schedule(request: ScheduleRequest) -> ScheduleResponse:
    """
    Main scheduling endpoint — called by Flutter after the onboarding popup
    collects all required information.
    """
    try:
        return scheduler.generate(request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scheduling failed: {str(e)}",
        )


# ─────────────────────────────────────────────
# Canvas Router
# ─────────────────────────────────────────────

canvas_router = APIRouter(prefix="/canvas", tags=["Canvas LMS"])


@canvas_router.post(
    "/validate",
    summary="Validate a Canvas access token",
    description="Confirms the token is valid and returns the student's Canvas profile.",
)
async def validate_canvas_token(request: CanvasTokenRequest) -> dict:
    svc = CanvasService(request.canvas_domain, request.access_token)
    try:
        user_info = await svc.validate_token()
        return {
            "valid": True,
            "canvas_user_id": user_info.get("id"),
            "name": user_info.get("name"),
            "email": user_info.get("email"),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Canvas token validation failed: {str(e)}",
        )


@canvas_router.post(
    "/assignments",
    response_model=list[CanvasAssignment],
    summary="Fetch upcoming Canvas assignments",
    description=(
        "Returns all assignments due within the next `lookahead_days` days "
        "across all active courses. The Flutter app uses this to populate "
        "the onboarding popup where students assign time estimates."
    ),
)
async def get_canvas_assignments(request: CanvasTokenRequest) -> list[CanvasAssignment]:
    svc = CanvasService(request.canvas_domain, request.access_token)
    try:
        return await svc.get_upcoming_assignments(request.lookahead_days)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch Canvas assignments: {str(e)}",
        )
