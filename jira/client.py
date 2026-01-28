"""
Jira API client for fetching tasks, boards, and issue statuses.
"""

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


class TaskStatus(Enum):
    """Task status categories."""
    IN_PROGRESS = "in_progress"
    CLOSED_TODAY = "closed_today"
    TODO = "todo"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class JiraTask:
    """Represents a Jira issue/task."""
    key: str
    summary: str
    status: str
    status_category: str
    issue_type: str
    project_key: str
    project_name: str
    assignee: Optional[str]
    priority: Optional[str]
    description: Optional[str]
    created: str
    updated: str
    resolution_date: Optional[str]
    custom_closed_date: Optional[str]
    custom_start_date: Optional[str]
    labels: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "status_category": self.status_category,
            "type": self.issue_type,
            "project": self.project_name,
            "project_key": self.project_key,
            "assignee": self.assignee,
            "priority": self.priority,
            "description": self.description[:200] if self.description else None,
            "created": self.created,
            "updated": self.updated,
            "resolution_date": self.resolution_date,
            "closed_date": self.custom_closed_date,
            "start_date": self.custom_start_date,
            "labels": self.labels,
            "components": self.components,
            "url": self.url
        }


@dataclass
class JiraBoardInfo:
    """Represents a Jira board summary."""
    board_id: int
    name: str
    type: str
    project_key: Optional[str]
    tasks_in_progress: int = 0
    tasks_done: int = 0
    tasks_todo: int = 0


class JiraClient:
    """Client for interacting with Jira API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.base_url = (base_url or os.getenv("JIRA_URL", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")
        self.timeout = timeout

        # Custom field names for dates (can be customized via env)
        self.closed_date_field = os.getenv("JIRA_CLOSED_DATE_FIELD", "customfield_10100")
        self.start_date_field = os.getenv("JIRA_START_DATE_FIELD", "customfield_10101")

        if not all([self.base_url, self.email, self.api_token]):
            raise ValueError(
                "JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN environment variables must be set"
            )

        self.api_url = f"{self.base_url}/rest/api/3"
        self.agile_api_url = f"{self.base_url}/rest/agile/1.0"

    def _get_auth(self) -> httpx.BasicAuth:
        """Get basic auth for Jira API."""
        return httpx.BasicAuth(self.email, self.api_token)

    async def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make an async HTTP request to Jira API."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                auth=self._get_auth(),
                params=params,
                json=json_data,
                headers={"Accept": "application/json", "Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json()

    async def get_current_user(self) -> Dict[str, Any]:
        """Get the currently authenticated user."""
        return await self._make_request("GET", f"{self.api_url}/myself")

    async def search_issues(
        self,
        jql: str,
        max_results: int = 100,
        start_at: int = 0,
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Search for issues using JQL (new API endpoint)."""
        default_fields = [
            "summary", "status", "issuetype", "project", "assignee",
            "priority", "description", "created", "updated", "labels",
            "components", "resolutiondate",
            self.closed_date_field, self.start_date_field
        ]
        
        # Use query parameters for the new /search/jql endpoint
        params = {
            "jql": jql,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": ",".join(fields or default_fields)
        }

        return await self._make_request(
            "GET",
            f"{self.api_url}/search/jql",
            params=params
        )

    async def get_my_tasks(
        self,
        include_done: bool = True,
        additional_jql: Optional[str] = None
    ) -> List[JiraTask]:
        """Get all tasks assigned to current user."""
        try:
            user = await self.get_current_user()
            account_id = user.get("accountId")

            jql_parts = [f"assignee = '{account_id}'"]
            
            if not include_done:
                jql_parts.append("status != Done")
            
            if additional_jql:
                jql_parts.append(f"({additional_jql})")
            
            jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
            
            logger.info(f"Searching Jira with JQL: {jql}")
            
            result = await self.search_issues(jql)
            issues = result.get("issues", [])
            
            tasks = [self._parse_issue(issue) for issue in issues]
            logger.info(f"Found {len(tasks)} tasks assigned to user")
            
            return tasks

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get tasks: {e.response.status_code} - {e.response.text}")
            return []

    async def get_tasks_in_progress(self) -> List[JiraTask]:
        """Get all tasks currently in progress for the user."""
        try:
            user = await self.get_current_user()
            account_id = user.get("accountId")

            jql = (
                f"assignee = '{account_id}' AND "
                f"statusCategory = 'In Progress' "
                f"ORDER BY updated DESC"
            )

            result = await self.search_issues(jql)
            issues = result.get("issues", [])
            
            tasks = [self._parse_issue(issue) for issue in issues]
            logger.info(f"Found {len(tasks)} tasks in progress")
            
            return tasks

        except Exception as e:
            logger.error(f"Failed to get in-progress tasks: {e}")
            return []

    async def get_tasks_closed_today(self) -> List[JiraTask]:
        """Get tasks that were closed today based on custom date field or resolution date."""
        try:
            user = await self.get_current_user()
            account_id = user.get("accountId")
            
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Try both resolution date and custom closed date field
            jql = (
                f"assignee = '{account_id}' AND "
                f"(resolutiondate >= '{today}' OR "
                f"{self.closed_date_field} >= '{today}') "
                f"ORDER BY updated DESC"
            )

            try:
                result = await self.search_issues(jql)
            except httpx.HTTPStatusError:
                # Fallback if custom field doesn't exist
                jql = (
                    f"assignee = '{account_id}' AND "
                    f"resolutiondate >= '{today}' "
                    f"ORDER BY updated DESC"
                )
                result = await self.search_issues(jql)

            issues = result.get("issues", [])
            tasks = [self._parse_issue(issue) for issue in issues]
            
            logger.info(f"Found {len(tasks)} tasks closed today")
            return tasks

        except Exception as e:
            logger.error(f"Failed to get closed tasks: {e}")
            return []

    async def get_boards(self) -> List[JiraBoardInfo]:
        """Get all accessible Jira boards."""
        try:
            result = await self._make_request(
                "GET",
                f"{self.agile_api_url}/board",
                params={"maxResults": 50}
            )

            boards = []
            for board_data in result.get("values", []):
                board = JiraBoardInfo(
                    board_id=board_data.get("id"),
                    name=board_data.get("name", ""),
                    type=board_data.get("type", ""),
                    project_key=board_data.get("location", {}).get("projectKey")
                )
                boards.append(board)

            logger.info(f"Found {len(boards)} boards")
            return boards

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Agile API not available, skipping boards")
            else:
                logger.error(f"Failed to get boards: {e.response.status_code}")
            return []

    async def get_board_issues_summary(self, board_id: int) -> Dict[str, int]:
        """Get a summary of issues on a specific board."""
        try:
            result = await self._make_request(
                "GET",
                f"{self.agile_api_url}/board/{board_id}/issue",
                params={"maxResults": 100, "fields": "status"}
            )

            summary = {
                "todo": 0,
                "in_progress": 0,
                "done": 0
            }

            for issue in result.get("issues", []):
                status_category = (
                    issue.get("fields", {})
                    .get("status", {})
                    .get("statusCategory", {})
                    .get("key", "")
                )
                
                if status_category == "new":
                    summary["todo"] += 1
                elif status_category == "indeterminate":
                    summary["in_progress"] += 1
                elif status_category == "done":
                    summary["done"] += 1

            return summary

        except Exception as e:
            logger.error(f"Failed to get board summary: {e}")
            return {"todo": 0, "in_progress": 0, "done": 0}

    def _parse_issue(self, issue: Dict[str, Any]) -> JiraTask:
        """Parse a Jira issue into a JiraTask object."""
        fields = issue.get("fields", {})
        
        # Extract status info
        status_obj = fields.get("status", {})
        status = status_obj.get("name", "Unknown")
        status_category = status_obj.get("statusCategory", {}).get("name", "Unknown")

        # Extract assignee
        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName") if assignee_obj else None

        # Extract priority
        priority_obj = fields.get("priority")
        priority = priority_obj.get("name") if priority_obj else None

        # Extract project info
        project_obj = fields.get("project", {})
        
        # Extract labels and components
        labels = fields.get("labels", [])
        components = [c.get("name", "") for c in fields.get("components", [])]

        # Extract custom date fields
        closed_date = fields.get(self.closed_date_field)
        start_date = fields.get(self.start_date_field)

        # Build issue URL
        issue_key = issue.get("key", "")
        issue_url = f"{self.base_url}/browse/{issue_key}" if issue_key else ""

        # Extract description (handle Atlassian Document Format)
        description = None
        desc_field = fields.get("description")
        if desc_field:
            if isinstance(desc_field, str):
                description = desc_field
            elif isinstance(desc_field, dict):
                # ADF format - extract text from content
                description = self._extract_text_from_adf(desc_field)

        return JiraTask(
            key=issue_key,
            summary=fields.get("summary", ""),
            status=status,
            status_category=status_category,
            issue_type=fields.get("issuetype", {}).get("name", "Task"),
            project_key=project_obj.get("key", ""),
            project_name=project_obj.get("name", ""),
            assignee=assignee,
            priority=priority,
            description=description,
            created=fields.get("created", ""),
            updated=fields.get("updated", ""),
            resolution_date=fields.get("resolutiondate"),
            custom_closed_date=closed_date,
            custom_start_date=start_date,
            labels=labels,
            components=components,
            url=issue_url
        )

    def _extract_text_from_adf(self, adf: Dict[str, Any], max_length: int = 500) -> str:
        """Extract plain text from Atlassian Document Format."""
        text_parts = []

        def extract_content(node: Any):
            if isinstance(node, dict):
                if node.get("type") == "text":
                    text_parts.append(node.get("text", ""))
                for child in node.get("content", []):
                    extract_content(child)
            elif isinstance(node, list):
                for item in node:
                    extract_content(item)

        extract_content(adf)
        full_text = " ".join(text_parts)
        
        return full_text[:max_length] if len(full_text) > max_length else full_text


async def fetch_jira_tasks() -> Dict[str, Any]:
    """
    Fetch all relevant Jira data for today's report.

    Returns:
        Dictionary containing:
        - tasks_in_progress: List of tasks currently being worked on
        - tasks_closed_today: List of tasks closed today
        - all_my_tasks: All tasks assigned to user
        - boards_summary: Summary of boards
    """
    try:
        client = JiraClient()
        
        # Fetch all data concurrently
        import asyncio
        
        tasks_in_progress, tasks_closed_today, all_tasks, boards = await asyncio.gather(
            client.get_tasks_in_progress(),
            client.get_tasks_closed_today(),
            client.get_my_tasks(include_done=False),
            client.get_boards(),
            return_exceptions=True
        )

        # Handle any exceptions from concurrent calls
        if isinstance(tasks_in_progress, Exception):
            logger.error(f"Error fetching in-progress tasks: {tasks_in_progress}")
            tasks_in_progress = []
        
        if isinstance(tasks_closed_today, Exception):
            logger.error(f"Error fetching closed tasks: {tasks_closed_today}")
            tasks_closed_today = []
        
        if isinstance(all_tasks, Exception):
            logger.error(f"Error fetching all tasks: {all_tasks}")
            all_tasks = []
        
        if isinstance(boards, Exception):
            logger.error(f"Error fetching boards: {boards}")
            boards = []

        return {
            "tasks_in_progress": [t.to_dict() for t in tasks_in_progress],
            "tasks_closed_today": [t.to_dict() for t in tasks_closed_today],
            "all_my_tasks": [t.to_dict() for t in all_tasks],
            "boards": [
                {
                    "id": b.board_id,
                    "name": b.name,
                    "type": b.type,
                    "project": b.project_key
                }
                for b in boards
            ]
        }

    except Exception as e:
        logger.error(f"Error fetching Jira data: {e}")
        return {
            "tasks_in_progress": [],
            "tasks_closed_today": [],
            "all_my_tasks": [],
            "boards": []
        }
