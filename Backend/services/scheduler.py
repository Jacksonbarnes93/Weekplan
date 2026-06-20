"""
Student Scheduling Algorithm
─────────────────────────────
Strategy overview:
  1. Parse all available time windows for the week into 15-minute slots.
  2. Block out all fixed events (classes, jobs, meetings).
  3. Sort tasks by a priority score that combines:
       - Due date urgency (closer = higher priority)
       - Buffer preference (try to finish N days early)
       - Difficulty + energy preference alignment
  4. For each task (highest priority first):
       a. Split into sessions if max_session_minutes is set.
       b. Find the best slot(s) that align with energy preference.
       c. Insert work block + optional surrounding breaks.
  5. If the week fills up, collect overflow warnings.
  6. If allow_overflow=True, schedule remaining tasks outside normal windows.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from models.schemas import (
    DayOfWeek, DifficultyLevel, EnergyPreference, FixedEvent,
    ScheduleRequest, ScheduleResponse, ScheduleWarning,
    ScheduledBlock, DaySchedule, Task, TimeWindow, UserPreferences,
)

# Slot size in minutes — all scheduling is done in these increments
SLOT_MINUTES = 15

# Maps DayOfWeek enum to Python weekday index (Monday=0)
DAY_INDEX = {
    DayOfWeek.MONDAY: 0, DayOfWeek.TUESDAY: 1, DayOfWeek.WEDNESDAY: 2,
    DayOfWeek.THURSDAY: 3, DayOfWeek.FRIDAY: 4,
    DayOfWeek.SATURDAY: 5, DayOfWeek.SUNDAY: 6,
}

# Inverse map: weekday index → DayOfWeek
INDEX_DAY = {v: k for k, v in DAY_INDEX.items()}


# ─────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────

def _parse_hhmm(hhmm: str) -> int:
    """Convert 'HH:MM' → minutes since midnight."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _to_hhmm(minutes_since_midnight: int) -> str:
    """Convert minutes since midnight → 'HH:MM'."""
    h = minutes_since_midnight // 60
    m = minutes_since_midnight % 60
    return f"{h:02d}:{m:02d}"

def _round_up_slot(minutes: int) -> int:
    """Round minutes up to the nearest SLOT_MINUTES boundary."""
    return ((minutes + SLOT_MINUTES - 1) // SLOT_MINUTES) * SLOT_MINUTES

def _day_date(week_start: date, day: DayOfWeek) -> date:
    """Return the calendar date for a given DayOfWeek in the current week."""
    return week_start + timedelta(days=DAY_INDEX[day])

def _energy_window(pref: EnergyPreference) -> tuple[int, int]:
    """Return (start_min, end_min) of the preferred energy window."""
    windows = {
        EnergyPreference.MORNING: (360, 720),    # 6am–12pm
        EnergyPreference.MIDDAY:  (720, 1020),   # 12pm–5pm
        EnergyPreference.EVENING: (1020, 1380),  # 5pm–11pm
        EnergyPreference.NO_PREF: (0, 1440),
    }
    return windows[pref]


# ─────────────────────────────────────────────
# Slot Grid
# ─────────────────────────────────────────────

class SlotGrid:
    """
    Represents a full week as a grid of 15-minute boolean slots.
    True  = available for scheduling
    False = blocked (fixed event, outside window, already assigned)
    """

    def __init__(self):
        # 7 days × 96 slots/day (24h × 4 per hour)
        self._slots: dict[DayOfWeek, list[Optional[str]]] = {
            day: [None] * (24 * 60 // SLOT_MINUTES)
            for day in DayOfWeek
        }
        # Mark everything as unavailable initially
        for day in DayOfWeek:
            for i in range(len(self._slots[day])):
                self._slots[day][i] = "unavailable"

    def open_window(self, day: DayOfWeek, start_min: int, end_min: int):
        """Mark a time window as available (free)."""
        start_slot = start_min // SLOT_MINUTES
        end_slot   = end_min   // SLOT_MINUTES
        for i in range(start_slot, end_slot):
            if self._slots[day][i] == "unavailable":
                self._slots[day][i] = None  # None = free

    def block(self, day: DayOfWeek, start_min: int, end_min: int, label: str):
        """Block a range of slots with a label."""
        start_slot = start_min // SLOT_MINUTES
        end_slot   = min(end_min // SLOT_MINUTES, len(self._slots[day]))
        for i in range(start_slot, end_slot):
            self._slots[day][i] = label

    def find_free_slots(
        self,
        day: DayOfWeek,
        duration_slots: int,
        preferred_start: Optional[int] = None,
        preferred_end: Optional[int]   = None,
        allow_overflow: bool            = False,
    ) -> Optional[int]:
        """
        Find the first contiguous run of `duration_slots` free slots on `day`.
        Prefers slots within (preferred_start, preferred_end) window first.
        Falls back to any free slot if preference not found.
        Returns start slot index or None.
        """
        total = len(self._slots[day])

        def _scan(from_slot: int, to_slot: int) -> Optional[int]:
            run = 0
            for i in range(from_slot, to_slot):
                state = self._slots[day][i]
                is_free = (state is None) or (allow_overflow and state == "unavailable")
                if is_free:
                    run += 1
                    if run >= duration_slots:
                        return i - duration_slots + 1
                else:
                    run = 0
            return None

        # Try energy-preferred window first
        if preferred_start is not None and preferred_end is not None:
            ps = preferred_start // SLOT_MINUTES
            pe = preferred_end   // SLOT_MINUTES
            result = _scan(ps, min(pe, total))
            if result is not None:
                return result

        # Fall back to full available window
        return _scan(0, total)

    def place(self, day: DayOfWeek, start_slot: int, duration_slots: int, label: str):
        """Mark slots as occupied with a label."""
        for i in range(start_slot, start_slot + duration_slots):
            if i < len(self._slots[day]):
                self._slots[day][i] = label

    def free_minutes(self, day: DayOfWeek) -> int:
        return sum(1 for s in self._slots[day] if s is None) * SLOT_MINUTES

    def total_available_minutes(self, day: DayOfWeek) -> int:
        return sum(1 for s in self._slots[day] if s is not None and s != "unavailable") * SLOT_MINUTES


# ─────────────────────────────────────────────
# Priority Scoring
# ─────────────────────────────────────────────

def _priority_score(task: Task, week_start: date, buffer_days: int) -> float:
    """
    Higher score = schedule earlier.

    Components:
      - Urgency (0–100):  100 if due today, 0 if due 7+ days away
      - Buffer penalty:   Treat the effective deadline as (due_date - buffer_days)
      - Difficulty bonus: Harder tasks get a small boost so they land in
                          energy-preferred windows earlier in the week
    """
    effective_due = task.due_date.date() - timedelta(days=buffer_days)
    days_until_due = (effective_due - week_start).days

    # Clamp to [0, 7]
    days_until_due = max(0, min(7, days_until_due))
    urgency = (7 - days_until_due) / 7 * 100

    difficulty_bonus = (task.difficulty.value - 1) * 5  # 0, 5, or 10

    return urgency + difficulty_bonus


# ─────────────────────────────────────────────
# Main Scheduler
# ─────────────────────────────────────────────

class StudentScheduler:

    def generate(self, request: ScheduleRequest) -> ScheduleResponse:
        tz = ZoneInfo(request.timezone)
        week_start = date.fromisoformat(request.week_start_date)
        prefs = request.preferences

        # ── Step 1: Build slot grid ──────────────────────────────────────
        grid = SlotGrid()
        self._open_available_windows(grid, request.available_windows)

        # ── Step 2: Block fixed events ───────────────────────────────────
        fixed_blocks: list[ScheduledBlock] = []
        for event in request.fixed_events:
            start_m = _parse_hhmm(event.start_time)
            end_m   = _parse_hhmm(event.end_time)
            grid.block(event.day, start_m, end_m, f"fixed:{event.id}")
            fixed_blocks.append(ScheduledBlock(
                block_id   = f"fixed-{event.id}",
                title      = event.title,
                day        = event.day,
                start_time = event.start_time,
                end_time   = event.end_time,
                block_type = "fixed",
                notes      = event.notes,
            ))

        # ── Step 3: Sort tasks by priority ───────────────────────────────
        sorted_tasks = sorted(
            request.tasks,
            key=lambda t: _priority_score(t, week_start, prefs.buffer_days_before_due),
            reverse=True,
        )

        # ── Step 4: Schedule each task ───────────────────────────────────
        work_blocks: list[ScheduledBlock]     = []
        warnings: list[ScheduleWarning]       = []
        scheduled_ids: list[str]              = []
        unscheduled_ids: list[str]            = []

        e_start, e_end = _energy_window(prefs.energy_preference)

        for task in sorted_tasks:
            sessions = self._split_into_sessions(task)
            all_placed = True

            for session_minutes in sessions:
                placed = self._place_session(
                    grid         = grid,
                    task         = task,
                    session_min  = session_minutes,
                    week_start   = week_start,
                    prefs        = prefs,
                    e_start      = e_start,
                    e_end        = e_end,
                    work_blocks  = work_blocks,
                    allow_overflow = False,
                )
                if not placed:
                    all_placed = False

            if not all_placed:
                if prefs.allow_overflow:
                    # Try again with overflow allowed
                    for session_minutes in sessions:
                        self._place_session(
                            grid         = grid,
                            task         = task,
                            session_min  = session_minutes,
                            week_start   = week_start,
                            prefs        = prefs,
                            e_start      = e_start,
                            e_end        = e_end,
                            work_blocks  = work_blocks,
                            allow_overflow = True,
                        )
                    scheduled_ids.append(task.id)
                    warnings.append(ScheduleWarning(
                        code               = "OVERFLOW",
                        message            = f'"{task.title}" was scheduled outside your normal hours.',
                        affected_task_ids  = [task.id],
                    ))
                else:
                    unscheduled_ids.append(task.id)
                    warnings.append(ScheduleWarning(
                        code               = "UNSCHEDULED",
                        message            = (
                            f'"{task.title}" could not fit in your week. '
                            "Enable overflow or reduce other commitments."
                        ),
                        affected_task_ids  = [task.id],
                    ))
            else:
                scheduled_ids.append(task.id)

        # ── Step 5: Assemble day-by-day response ─────────────────────────
        all_blocks = fixed_blocks + work_blocks
        days = self._assemble_days(all_blocks, week_start, grid)

        return ScheduleResponse(
            user_id                 = request.user_id,
            week_start_date         = request.week_start_date,
            days                    = days,
            warnings                = warnings,
            total_tasks_scheduled   = len(scheduled_ids),
            total_tasks_unscheduled = len(unscheduled_ids),
            unscheduled_task_ids    = unscheduled_ids,
            overflow_enabled        = prefs.allow_overflow,
            generated_at            = datetime.now(timezone.utc),
        )

    # ─────────────────────────────────────────────
    # Internal Helpers
    # ─────────────────────────────────────────────

    def _open_available_windows(self, grid: SlotGrid, windows: list[TimeWindow]):
        for w in windows:
            grid.open_window(w.day, _parse_hhmm(w.start_time), _parse_hhmm(w.end_time))

    def _split_into_sessions(self, task: Task) -> list[int]:
        """
        If the task has a max_session_minutes limit, split the total estimated
        time into chunks. Returns a list of session durations in minutes.
        """
        total = task.estimated_minutes
        max_s = task.max_session_minutes

        if not max_s or total <= max_s:
            return [_round_up_slot(total)]

        sessions = []
        remaining = total
        while remaining > 0:
            chunk = min(max_s, remaining)
            sessions.append(_round_up_slot(chunk))
            remaining -= chunk
        return sessions

    def _place_session(
        self,
        grid: SlotGrid,
        task: Task,
        session_min: int,
        week_start: date,
        prefs: UserPreferences,
        e_start: int,
        e_end: int,
        work_blocks: list[ScheduledBlock],
        allow_overflow: bool,
    ) -> bool:
        """
        Try to place one session of `session_min` minutes on the best available day.
        Respects buffer days, energy preference, and break settings.
        Returns True if placed successfully.
        """
        duration_slots = session_min // SLOT_MINUTES
        break_slots    = prefs.break_between_sessions_minutes // SLOT_MINUTES

        # Effective deadline: due_date minus buffer
        effective_due_date = task.due_date.date() - timedelta(days=prefs.buffer_days_before_due)

        # Determine which days are candidates (due date or earlier, within this week)
        candidate_days = []
        for day_enum in DayOfWeek:
            day_date_val = _day_date(week_start, day_enum)
            if day_date_val <= effective_due_date:
                candidate_days.append(day_enum)

        # Sort candidates: prefer days where energy window has more free time
        def day_score(d: DayOfWeek) -> float:
            free = grid.free_minutes(d)
            return free

        candidate_days.sort(key=day_score, reverse=True)

        for day in candidate_days:
            start_slot = grid.find_free_slots(
                day             = day,
                duration_slots  = duration_slots + break_slots,
                preferred_start = e_start,
                preferred_end   = e_end,
                allow_overflow  = allow_overflow,
            )
            if start_slot is None:
                continue

            # Place work block
            start_min = start_slot * SLOT_MINUTES
            end_min   = start_min + session_min
            grid.place(day, start_slot, duration_slots, f"task:{task.id}")

            is_overflow = (
                grid._slots[day][start_slot] == "unavailable"
                if allow_overflow else False
            )

            work_blocks.append(ScheduledBlock(
                block_id    = str(uuid.uuid4()),
                task_id     = task.id,
                title       = task.title,
                day         = day,
                start_time  = _to_hhmm(start_min),
                end_time    = _to_hhmm(end_min),
                block_type  = "overflow" if is_overflow else "work",
                course_name = task.course_name,
                notes       = task.notes,
                is_overflow = is_overflow,
            ))

            # Place gap break between sessions if requested
            if break_slots > 0:
                break_start = start_slot + duration_slots
                break_end   = break_start + break_slots
                grid.place(day, break_start, break_slots, "break")
                work_blocks.append(ScheduledBlock(
                    block_id   = str(uuid.uuid4()),
                    title      = "Break",
                    day        = day,
                    start_time = _to_hhmm(break_start * SLOT_MINUTES),
                    end_time   = _to_hhmm(break_end   * SLOT_MINUTES),
                    block_type = "break",
                ))

            # Auto-insert hourly micro-breaks if enabled
            if prefs.auto_breaks and session_min >= prefs.auto_break_interval_minutes:
                self._insert_auto_breaks(
                    grid, day, start_slot, duration_slots,
                    prefs.auto_break_interval_minutes,
                    prefs.auto_break_duration_minutes,
                    work_blocks,
                )

            return True

        return False  # Couldn't place this session

    def _insert_auto_breaks(
        self,
        grid: SlotGrid,
        day: DayOfWeek,
        work_start_slot: int,
        work_duration_slots: int,
        interval_min: int,
        break_min: int,
        work_blocks: list[ScheduledBlock],
    ):
        """Insert short breaks every `interval_min` minutes within a long work block."""
        interval_slots = interval_min // SLOT_MINUTES
        break_slots    = break_min    // SLOT_MINUTES
        offset = interval_slots

        while offset < work_duration_slots:
            b_start = work_start_slot + offset
            b_end   = b_start + break_slots
            grid.place(day, b_start, break_slots, "auto_break")
            work_blocks.append(ScheduledBlock(
                block_id   = str(uuid.uuid4()),
                title      = "Short Break",
                day        = day,
                start_time = _to_hhmm(b_start * SLOT_MINUTES),
                end_time   = _to_hhmm(b_end   * SLOT_MINUTES),
                block_type = "break",
            ))
            offset += interval_slots + break_slots

    def _assemble_days(
        self,
        all_blocks: list[ScheduledBlock],
        week_start: date,
        grid: SlotGrid,
    ) -> list[DaySchedule]:
        """Group blocks by day, sort by start time, compute stats."""
        days_map: dict[DayOfWeek, list[ScheduledBlock]] = {d: [] for d in DayOfWeek}
        for block in all_blocks:
            days_map[block.day].append(block)

        result = []
        for day_enum in DayOfWeek:
            blocks = sorted(
                days_map[day_enum],
                key=lambda b: _parse_hhmm(b.start_time),
            )
            work_minutes = sum(
                _parse_hhmm(b.end_time) - _parse_hhmm(b.start_time)
                for b in blocks if b.block_type in ("work", "overflow")
            )
            result.append(DaySchedule(
                date                = str(_day_date(week_start, day_enum)),
                day                 = day_enum,
                blocks              = blocks,
                total_work_minutes  = work_minutes,
                total_free_minutes  = grid.free_minutes(day_enum),
            ))

        return result
