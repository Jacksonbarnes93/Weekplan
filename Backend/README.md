# Student Scheduler API

FastAPI backend for the student productivity calendar app.  
Connects to Canvas LMS and generates optimized weekly schedules from student input.

---

## Project Structure

```
student_scheduler/
├── main.py                  # FastAPI app + CORS setup
├── requirements.txt
├── models/
│   └── schemas.py           # All Pydantic request/response models
├── routers/
│   └── api.py               # /schedule and /canvas endpoints
├── services/
│   ├── scheduler.py         # Core scheduling algorithm
│   └── canvas_service.py    # Canvas LMS API wrapper
└── example_request.json     # Test payload for /schedule/generate
```

---

## Setup

```bash
cd student_scheduler
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Interactive API docs: **http://localhost:8000/docs**

---

## How the Algorithm Works

### 1. Slot Grid
The week is divided into **15-minute slots** (96 slots/day × 7 days).  
All scheduling decisions happen at this resolution.

### 2. Available Windows
The student's open hours (e.g. 10:30am–11pm) are opened in the grid.  
Everything outside those windows starts as `unavailable`.

### 3. Fixed Events Blocked
Classes, jobs, meetings, and extracurriculars are blocked first —  
they are immovable.

### 4. Task Priority Scoring
Each task gets a score combining:
- **Urgency**: How many days until the effective deadline (due date minus buffer days). Closer = higher priority.
- **Difficulty bonus**: Harder tasks score slightly higher, nudging them into energy-preferred windows early in the week.

### 5. Scheduling Loop
Tasks are processed highest-priority first. For each task:
- If it has a `max_session_minutes`, it's split into multiple sessions.
- The algorithm finds the best day + time slot that fits:
  - Prefers the student's **energy window** (morning / midday / evening)
  - Prefers days with the most remaining free time (spread evenly)
  - Stays before the **effective due date** (due date − buffer days)
- Breaks are inserted between sessions and as hourly auto-breaks if enabled.

### 6. Overflow Handling
If a task can't fit in normal hours:
- If `allow_overflow = false` → task goes to `unscheduled_task_ids` + warning.
- If `allow_overflow = true` → placed outside available windows, marked as overflow.

---

## API Endpoints

### `POST /schedule/generate`
Main endpoint. Call this after the onboarding popup collects everything.

**Request body**: See `example_request.json`

**Response includes**:
- `days[]` — Each day of the week with sorted time blocks
- `warnings[]` — Overflow or unscheduled task warnings
- `unscheduled_task_ids[]` — Tasks that couldn't fit

---

### `POST /canvas/validate`
Validate a student's Canvas access token before fetching assignments.

```json
{
  "canvas_domain": "canvas.youruniversity.edu",
  "access_token": "TOKEN_HERE",
  "lookahead_days": 7
}
```

---

### `POST /canvas/assignments`
Fetch all upcoming assignments from Canvas (due within `lookahead_days`).  
Returns a list the Flutter app can display in the onboarding popup for time estimation.

```json
{
  "canvas_domain": "canvas.youruniversity.edu",
  "access_token": "TOKEN_HERE",
  "lookahead_days": 7
}
```

---

## Flutter Integration Flow

```
App opens (start of week)
        │
        ▼
POST /canvas/validate     ← Student enters Canvas domain + token
        │
        ▼
POST /canvas/assignments  ← Load this week's assignments
        │
        ▼
Onboarding Popup          ← For each assignment: ask estimated minutes + difficulty
                          ← Add fixed events (classes, jobs, activities)
                          ← Set available hours per day
                          ← Set preferences (energy, buffer, breaks)
        │
        ▼
POST /schedule/generate   ← Send full ScheduleRequest
        │
        ▼
Display week calendar     ← Render DaySchedule[] blocks
```

---

## Canvas Access Token

Students generate a personal access token in Canvas:  
**Account → Settings → New Access Token**

For production, implement the full **Canvas OAuth2 flow** instead.  
Docs: https://canvas.instructure.com/doc/api/file.oauth.html

---

## Extending the Algorithm

| Feature | Where to add it |
|---|---|
| ML-based time estimation | Add a prediction model in `services/` trained on past task durations |
| Recurring study habits | Add a `recurring_tasks` field to `ScheduleRequest` |
| Google Calendar sync | New router + service similar to `canvas_service.py` |
| Per-course difficulty weights | Add `course_difficulty_map` to `UserPreferences` |
| Pomodoro mode | Set `max_session_minutes=25`, `break_between_sessions_minutes=5` |
