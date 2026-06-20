from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class DayOfWeek(str, Enum):
    MONDAY    = "monday"
    TUESDAY   = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY  = "thursday"
    FRIDAY    = "friday"
    SATURDAY  = "saturday"
    SUNDAY    = "sunday"

class EnergyPreference(str, Enum):
    MORNING   = "morning"    # Prefers hard work 6am–12pm
    MIDDAY    = "midday"     # Prefers hard work 12pm–5pm
    EVENING   = "evening"    # Prefers hard work 5pm–11pm
    NO_PREF   = "no_preference"

class TaskType(str, Enum):
    ASSIGNMENT  = "assignment"
    STUDY       = "study"
    PROJECT     = "project"
    READING     = "reading"
    OTHER       = "other"

class EventType(str, Enum):
    CLASS           = "class"
    MEETING         = "meeting"
    EXTRACURRICULAR = "extracurricular"
    JOB             = "job"
    PERSONAL        = "personal"
    OTHER           = "other"

class DifficultyLevel(int, Enum):
    EASY   = 1
    MEDIUM = 2
    HARD   = 3


# ─────────────────────────────────────────────
# Input Models
# ─────────────────────────────────────────────

class TimeWindow(BaseModel):
    """A student's available working window on a given day."""
    day: DayOfWeek
    start_time: str = Field(..., description="HH:MM in 24h format, e.g. '10:30'")
    end_time: str   = Field(..., description="HH:MM in 24h format, e.g. '23:00'")


class FixedEvent(BaseModel):
    """A non-movable block on the calendar (class, job shift, meeting, etc.)."""
    id: str
    title: str
    event_type: EventType
    day: DayOfWeek
    start_time: str  = Field(..., description="HH:MM 24h")
    end_time: str    = Field(..., description="HH:MM 24h")
    recurring: bool  = True   # Does it repeat every week?
    notes: Optional[str] = None


class Task(BaseModel):
    """A piece of work the student needs to schedule (from Canvas or manual)."""
    id: str
    title: str
    task_type: TaskType
    course_name: Optional[str] = None
    due_date: datetime          = Field(..., description="Full due date/time in ISO format")
    estimated_minutes: int      = Field(..., ge=15, description="How long the student thinks it will take")
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    # If the student wants to break this into multiple sessions
    max_session_minutes: Optional[int] = Field(
        None, description="Max minutes per sitting. None = schedule as one block."
    )
    notes: Optional[str] = None


class UserPreferences(BaseModel):
    """Student scheduling preferences collected in the onboarding popup."""
    energy_preference: EnergyPreference = EnergyPreference.NO_PREF
    # Break between work sessions (0 = no break)
    break_between_sessions_minutes: int = Field(0, ge=0, le=60)
    # Buffer before due date (e.g. 1 = finish work 1 day before it's due)
    buffer_days_before_due: int = Field(1, ge=0, le=3)
    # Whether to auto-insert a short break every hour of study
    auto_breaks: bool = True
    auto_break_interval_minutes: int = Field(60, ge=30, le=120)
    auto_break_duration_minutes: int = Field(10, ge=5, le=30)
    # Override: allow scheduling outside normal available windows if overscheduled
    allow_overflow: bool = False


class ScheduleRequest(BaseModel):
    """
    The full payload the Flutter frontend sends to /schedule/generate.
    Combines everything collected during onboarding.
    """
    user_id: str
    week_start_date: str   = Field(..., description="ISO date of Monday, e.g. '2025-09-01'")
    timezone: str          = Field("America/Denver", description="IANA timezone string")
    available_windows: list[TimeWindow]
    fixed_events: list[FixedEvent]
    tasks: list[Task]
    preferences: UserPreferences


class CanvasTokenRequest(BaseModel):
    canvas_domain: str  = Field(..., description="e.g. 'canvas.university.edu'")
    access_token: str   = Field(..., description="OAuth token from Canvas")
    lookahead_days: int = Field(7, ge=1, le=30)


# ─────────────────────────────────────────────
# Output Models
# ─────────────────────────────────────────────

class ScheduledBlock(BaseModel):
    """One time block placed on the calendar."""
    block_id: str
    task_id: Optional[str]          = None   # None for breaks / fixed events
    title: str
    day: DayOfWeek
    start_time: str                          # HH:MM
    end_time: str                            # HH:MM
    block_type: str                          # "work" | "break" | "fixed" | "overflow"
    course_name: Optional[str]      = None
    notes: Optional[str]            = None
    is_overflow: bool               = False  # Outside normal available window


class DaySchedule(BaseModel):
    date: str                                # ISO date e.g. "2025-09-01"
    day: DayOfWeek
    blocks: list[ScheduledBlock]
    total_work_minutes: int
    total_free_minutes: int


class ScheduleWarning(BaseModel):
    code: str
    message: str
    affected_task_ids: list[str] = []


class ScheduleResponse(BaseModel):
    user_id: str
    week_start_date: str
    days: list[DaySchedule]
    warnings: list[ScheduleWarning]
    total_tasks_scheduled: int
    total_tasks_unscheduled: int
    unscheduled_task_ids: list[str]
    overflow_enabled: bool
    generated_at: datetime


class CanvasAssignment(BaseModel):
    """Simplified Canvas assignment returned to the frontend."""
    canvas_id: str
    title: str
    course_name: str
    due_date: Optional[datetime]
    points_possible: Optional[float]
    submission_type: Optional[str]
    html_url: str
