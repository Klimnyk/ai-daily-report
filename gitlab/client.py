"""
GitLab API client for fetching commits across all accessible projects.
"""

import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
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
class Commit:
    """Represents a GitLab commit."""
    project_name: str
    project_path: str
    message: str
    short_id: str
    committed_date: str
    web_url: str
    author_name: str
    author_email: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project_name,
            "project_path": self.project_path,
            "message": self.message.split("\n")[0],  # Only first line
            "short_id": self.short_id,
            "date": self.committed_date,
            "url": self.web_url,
            "author": {
                "name": self.author_name,
                "email": self.author_email
            }
        }


class GitLabClient:
    """Client for interacting with GitLab API."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0
    ):
        self.token = token or os.getenv("GITLAB_TOKEN")
        self.base_url = (base_url or os.getenv("GITLAB_URL", "https://gitlab.com")).rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"
        self.timeout = timeout

        if not self.token:
            raise ValueError("GITLAB_TOKEN environment variable is not set")

        self.headers = {
            "PRIVATE-TOKEN": self.token,
            "Content-Type": "application/json"
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make an async HTTP request to GitLab API."""
        url = f"{self.api_url}/{endpoint}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params
            )
            response.raise_for_status()
            return response.json()

    async def get_current_user(self) -> Dict[str, Any]:
        """Get the currently authenticated user."""
        try:
            return await self._make_request("GET", "user")
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get current user: {e.response.status_code}")
            raise

    async def get_user_projects(
        self,
        membership: bool = True,
        min_access_level: int = 30,  # Developer access
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """Get all projects where user has at least Developer access."""
        try:
            projects = []
            page = 1

            while True:
                params = {
                    "membership": str(membership).lower(),
                    "min_access_level": min_access_level,
                    "per_page": per_page,
                    "page": page,
                    "simple": "true"
                }
                
                page_projects = await self._make_request("GET", "projects", params)
                
                if not page_projects:
                    break
                    
                projects.extend(page_projects)
                
                if len(page_projects) < per_page:
                    break
                    
                page += 1

            logger.info(f"Found {len(projects)} accessible projects")
            return projects

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to get projects: {e.response.status_code}")
            return []

    async def get_project_commits(
        self,
        project_id: int,
        since: Optional[str] = None,
        until: Optional[str] = None,
        author_email: Optional[str] = None,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """Get commits for a specific project within date range."""
        try:
            params = {
                "per_page": per_page,
                "with_stats": "false"
            }
            
            if since:
                params["since"] = since
            if until:
                params["until"] = until

            commits = await self._make_request(
                "GET",
                f"projects/{project_id}/repository/commits",
                params
            )
            
            # Filter by author email if specified
            if author_email:
                commits = [
                    c for c in commits 
                    if c.get("author_email", "").lower() == author_email.lower()
                ]

            return commits

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"Project {project_id} not found or no access")
            else:
                logger.warning(f"Failed to get commits for project {project_id}: {e.response.status_code}")
            return []

    async def get_today_commits(
        self,
        filter_by_user: bool = True,
        project_ids: Optional[List[int]] = None
    ) -> List[Commit]:
        """
        Get all commits from today across all accessible projects.

        Args:
            filter_by_user: If True, only return commits from current user
            project_ids: Optional list of specific project IDs to check

        Returns:
            List of Commit objects
        """
        # Get today's date range in ISO format
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        since = today.isoformat()
        until = today.replace(hour=23, minute=59, second=59).isoformat()

        logger.info(f"Fetching commits from {since} to {until}")

        # Get current user email for filtering
        current_user_email = None
        if filter_by_user:
            try:
                user = await self.get_current_user()
                current_user_email = user.get("email")
                logger.info(f"Filtering commits for user: {current_user_email}")
            except Exception as e:
                logger.warning(f"Could not get current user, proceeding without filter: {e}")

        # Get projects to check
        if project_ids:
            projects = [{"id": pid, "name": f"project-{pid}", "path_with_namespace": f"project/{pid}"} for pid in project_ids]
        else:
            projects = await self.get_user_projects()

        all_commits: List[Commit] = []

        for project in projects:
            project_id = project["id"]
            project_name = project.get("name", "Unknown")
            project_path = project.get("path_with_namespace", "")

            commits_data = await self.get_project_commits(
                project_id=project_id,
                since=since,
                until=until,
                author_email=current_user_email
            )

            for commit_data in commits_data:
                commit = Commit(
                    project_name=project_name,
                    project_path=project_path,
                    message=commit_data.get("message", ""),
                    short_id=commit_data.get("short_id", ""),
                    committed_date=commit_data.get("committed_date", ""),
                    web_url=commit_data.get("web_url", ""),
                    author_name=commit_data.get("author_name", ""),
                    author_email=commit_data.get("author_email", "")
                )
                all_commits.append(commit)

            if commits_data:
                logger.info(f"Found {len(commits_data)} commits in {project_name}")

        logger.info(f"Total commits found today: {len(all_commits)}")
        return all_commits


async def fetch_gitlab_commits() -> List[Dict[str, Any]]:
    """
    Fetch all GitLab commits for today.

    Returns:
        List of commit dictionaries
    """
    try:
        client = GitLabClient()
        commits = await client.get_today_commits()
        return [commit.to_dict() for commit in commits]
    except Exception as e:
        logger.error(f"Error fetching GitLab commits: {e}")
        return []
