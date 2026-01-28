"""
Clockify API client for fetching time tracking data.
"""

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


@dataclass
class TimeEntry:
    """Represents a Clockify time entry."""
    description: str
    project_name: str
    task_name: Optional[str]
    duration_minutes: int
    start_time: str
    end_time: Optional[str]
    is_running: bool
    tags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.description or "No description",
            "project_name": self.project_name,
            "task": self.task_name,
            "time": self.duration_minutes,
            "start": self.start_time,
            "end": self.end_time,
            "is_running": self.is_running,
            "tags": self.tags
        }


class ClockifyClient:
    """Client for interacting with Clockify API."""

    BASE_URL = "https://api.clockify.me/api/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.api_key = api_key or os.getenv("CLOCKIFY_API_KEY")
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("CLOCKIFY_API_KEY is not set in environment variables")

        self.headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self.api_key
        }

        self._user_data: Optional[Dict[str, Any]] = None
        self._workspace_id: Optional[str] = None
        self._user_id: Optional[str] = None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make an async HTTP request to Clockify API."""
        url = f"{self.BASE_URL}/{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            return response.json()

    async def get_user_data(self) -> Dict[str, Any]:
        """Get the current user's data and cache it."""
        if self._user_data:
            return self._user_data

        try:
            self._user_data = await self._make_request("GET", "user")
            self._workspace_id = self._user_data.get("defaultWorkspace")
            self._user_id = self._user_data.get("id")
            return self._user_data
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching user data: {e.response.status_code}")
            raise

    async def get_time_entries(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        hydrated: bool = True
    ) -> List[Dict[str, Any]]:
        """Get time entries for a date range."""
        await self.get_user_data()

        if not self._workspace_id or not self._user_id:
            logger.error("Failed to get workspace ID or user ID")
            return []

        # Default to today if no dates provided
        if not start_date:
            start_date = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        if not end_date:
            end_date = start_date + timedelta(days=1, seconds=-1)

        params = {
            "start": start_date.isoformat().replace("+00:00", "Z"),
            "end": end_date.isoformat().replace("+00:00", "Z"),
            "hydrated": str(hydrated).lower()
        }

        try:
            endpoint = f"workspaces/{self._workspace_id}/user/{self._user_id}/time-entries"
            entries = await self._make_request("GET", endpoint, params=params)
            logger.info(f"Retrieved {len(entries)} time entries")
            return entries
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching time entries: {e.response.status_code}")
            return []

    async def get_today_entries(self) -> List[TimeEntry]:
        """Get all time entries for today."""
        raw_entries = await self.get_time_entries()
        entries = []

        for entry in raw_entries:
            time_entry = self._parse_entry(entry)
            entries.append(time_entry)

        return entries

    def _parse_entry(self, entry: Dict[str, Any]) -> TimeEntry:
        """Parse a raw API entry into a TimeEntry object."""
        # Extract project name
        project = entry.get("project")
        project_name = project.get("name", "No project") if project else "No project"

        # Extract task name
        task = entry.get("task")
        task_name = task.get("name") if task else None

        # Extract tags
        tags = [tag.get("name", "") for tag in entry.get("tags", [])]

        # Calculate duration
        time_interval = entry.get("timeInterval", {})
        start_time = time_interval.get("start", "")
        end_time = time_interval.get("end")
        
        duration_minutes = 0
        is_running = end_time is None

        if start_time and end_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                duration_minutes = int((end_dt - start_dt).total_seconds() // 60)
            except ValueError:
                pass

        return TimeEntry(
            description=entry.get("description", ""),
            project_name=project_name,
            task_name=task_name,
            duration_minutes=duration_minutes,
            start_time=start_time,
            end_time=end_time,
            is_running=is_running,
            tags=tags
        )

    async def get_projects(self) -> List[Dict[str, Any]]:
        """Get all projects in the workspace."""
        await self.get_user_data()

        if not self._workspace_id:
            return []

        try:
            return await self._make_request(
                "GET",
                f"workspaces/{self._workspace_id}/projects",
                params={"page-size": 100}
            )
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get projects: {e.response.status_code}")
            return []


async def get_formatted_today_time_entries() -> List[Dict[str, Any]]:
    """
    Get formatted time entries for today.

    Returns:
        List of time entry dictionaries with project_name, name, and time fields
    """
    try:
        client = ClockifyClient()
        entries = await client.get_today_entries()

        formatted = [entry.to_dict() for entry in entries]
        
        logger.info(f"Formatted {len(formatted)} time entries for today")
        
        if not formatted:
            logger.info("No time entries found for today")
        
        return formatted

    except Exception as e:
        logger.error(f"Error getting formatted time entries: {e}")
        return []


# Alias for backward compatibility
get_user_data = ClockifyClient().get_user_data
