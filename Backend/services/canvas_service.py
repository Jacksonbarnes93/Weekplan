"""
Canvas LMS API Service
Fetches assignments and courses from a student's Canvas account
using their personal access token (OAuth).

Canvas API docs: https://canvas.instructure.com/doc/api/
"""

import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from models.schemas import CanvasAssignment


class CanvasService:
    """Thin async wrapper around the Canvas REST API."""

    def __init__(self, domain: str, access_token: str):
        # Normalize domain — strip https:// if the user pasted the full URL
        self.domain = domain.replace("https://", "").replace("http://", "").rstrip("/")
        self.base_url = f"https://{self.domain}/api/v1"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # ─────────────────────────────────────────────
    # Public Methods
    # ─────────────────────────────────────────────

    async def validate_token(self) -> dict:
        """
        Ping the /users/self endpoint to confirm the token is valid.
        Returns basic user info dict on success, raises on failure.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/users/self",
                headers=self.headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_active_courses(self) -> list[dict]:
        """Return all currently active/enrolled courses for the student."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/courses",
                headers=self.headers,
                params={
                    "enrollment_state": "active",
                    "per_page": 50,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_upcoming_assignments(self, lookahead_days: int = 7) -> list[CanvasAssignment]:
        """
        Fetch all assignments due within the next `lookahead_days` days
        across all active courses.

        Returns a list of CanvasAssignment objects ready to hand to the
        onboarding popup so the student can assign time estimates.
        """
        courses = await self.get_active_courses()
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=lookahead_days)

        all_assignments: list[CanvasAssignment] = []

        async with httpx.AsyncClient() as client:
            for course in courses:
                course_id = course.get("id")
                course_name = course.get("name", "Unknown Course")

                # Skip courses without an ID (malformed responses)
                if not course_id:
                    continue

                assignments = await self._fetch_course_assignments(
                    client, course_id, course_name, now, cutoff
                )
                all_assignments.extend(assignments)

        # Sort by due date ascending (earliest due first)
        all_assignments.sort(key=lambda a: a.due_date or datetime.max.replace(tzinfo=timezone.utc))
        return all_assignments

    # ─────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────

    async def _fetch_course_assignments(
        self,
        client: httpx.AsyncClient,
        course_id: int,
        course_name: str,
        now: datetime,
        cutoff: datetime,
    ) -> list[CanvasAssignment]:
        """Fetch assignments for a single course, filtered to the lookahead window."""
        try:
            resp = await client.get(
                f"{self.base_url}/courses/{course_id}/assignments",
                headers=self.headers,
                params={
                    "bucket": "upcoming",   # Only upcoming/unsubmitted
                    "per_page": 100,
                    "order_by": "due_at",
                },
                timeout=15,
            )
            resp.raise_for_status()
            raw_assignments = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError):
            # Silently skip courses we can't read (e.g. observer-only access)
            return []

        result = []
        for a in raw_assignments:
            due_at_str = a.get("due_at")
            due_date: Optional[datetime] = None

            if due_at_str:
                try:
                    due_date = datetime.fromisoformat(due_at_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Filter: only include if due within our window
            if due_date and not (now <= due_date <= cutoff):
                continue

            result.append(CanvasAssignment(
                canvas_id=str(a.get("id", "")),
                title=a.get("name", "Untitled Assignment"),
                course_name=course_name,
                due_date=due_date,
                points_possible=a.get("points_possible"),
                submission_type=", ".join(a.get("submission_types", [])) or None,
                html_url=a.get("html_url", ""),
            ))

        return result
