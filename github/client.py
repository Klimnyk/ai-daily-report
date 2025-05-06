import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class GitHubClient:
    
    def __init__(self):
        self.token = os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GITHUB_TOKEN environment variable is not set")
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        self.graphql_url = "https://api.github.com/graphql"
    
    async def get_tasks_for_today(self, project_number: int = 5, owner: str = "Klimnyk") -> List[Dict[str, Any]]:
        today = datetime.now().date().isoformat()
        logger.info(f"Fetching tasks for date: {today}")
        
        project_id = await self._get_project_id(owner, project_number)
        if not project_id:
            logger.error(f"Could not find project {project_number} for user {owner}")
            return []
        query = """
        query($projectId: ID!) {
          node(id: $projectId) {
            ... on ProjectV2 {
              items(first: 100) {
                nodes {
                  id
                  content {
                    ... on Issue {
                      title
                      url
                      state
                      number
                      body
                    }
                    ... on DraftIssue {
                      title
                      body
                    }
                  }
                  fieldValues(first: 100) {
                    nodes {
                      ... on ProjectV2ItemFieldDateValue {
                        field {
                          ... on ProjectV2FieldCommon {
                            name
                          }
                        }
                        date
                      }
                      ... on ProjectV2ItemFieldTextValue {
                        field {
                          ... on ProjectV2FieldCommon {
                            name
                          }
                        }
                        text
                      }
                      ... on ProjectV2ItemFieldSingleSelectValue {
                        field {
                          ... on ProjectV2FieldCommon {
                            name
                          }
                        }
                        name
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        variables = {
            "projectId": project_id
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.graphql_url,
                    headers=self.headers,
                    json={"query": query, "variables": variables}
                )
                response.raise_for_status()
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL errors: {data['errors']}")
                    return []
                
                result = []
                for item in data["data"]["node"]["items"]["nodes"]:
                    task_data = {
                        "title": None,
                        "url": None,
                        "state": None,
                        "number": None,
                        "description": None,
                        "start_date": None,
                        "end_date": None,
                        "task_status": None
                    }
                    
                    if item["content"]:
                        if "title" in item["content"]:
                            task_data["title"] = item["content"]["title"]
                        if "url" in item["content"]:
                            task_data["url"] = item["content"]["url"]
                        if "state" in item["content"]:
                            task_data["state"] = item["content"]["state"]
                        if "number" in item["content"]:
                            task_data["number"] = item["content"]["number"]
                        if "body" in item["content"]: 
                            task_data["description"] = item["content"]["body"]
                    if item["fieldValues"]:
                        for field in item["fieldValues"]["nodes"]:
                            # Ensure 'field' and 'name' keys exist before accessing
                            if field.get("field") and "name" in field["field"]:
                                if field["field"]["name"] == "Status":
                                    task_data["task_status"] = field.get("name")
                                elif field["field"]["name"] == "Start date":
                                    task_data["start_date"] = field.get("date")
                                elif field["field"]["name"] == "End date":
                                    task_data["end_date"] = field.get("date")
  
                    
                    if task_data["start_date"] == today or task_data["end_date"] == today:
                        result.append(task_data)
                logger.info(f"Found {len(result)} tasks for today")
                return result
                
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred while fetching tasks: {e}")
            return []
        except Exception as e:
            logger.error(f"Error retrieving tasks from GitHub: {e}")
            return []

    async def _get_project_id(self, owner: str, project_number: int) -> Optional[str]:
        query = """
        query($owner: String!, $projectNumber: Int!) {
          user(login: $owner) {
            projectV2(number: $projectNumber) {
              id
            }
          }
        }
        """
        
        variables = {
            "owner": owner,
            "projectNumber": project_number
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.graphql_url,
                    headers=self.headers,
                    json={"query": query, "variables": variables}
                )
                response.raise_for_status()
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL errors: {data['errors']}")
                    return None
                
                return data["data"]["user"]["projectV2"]["id"]
        except Exception as e:
            logger.error(f"Error retrieving project ID: {e}")
            return None
    
        
    async def get_commits_for_today(self, owner: str = "Klimnyk", repos: Optional[List[str]] = None) -> List[Dict[str, Any]]:

        today = datetime.now().date().isoformat()
        logger.info(f"Fetching commits for date: {today}")
        
        # Get start and end of today in ISO format for GitHub API
        today_start = f"{today}T00:00:00Z"
        today_end = f"{today}T23:59:59Z"
        
        # If repos not provided, get user's repositories
        if not repos:
            repos = await self._get_user_repositories(owner)
        
        all_commits = []
        
        for repo in repos:
            logger.info(f"Checking commits in {owner}/{repo}")
            
            # Set up GraphQL query for commits
            query = """
            query($owner: String!, $repo: String!, $since: GitTimestamp!, $until: GitTimestamp!) {
                repository(owner: $owner, name: $repo) {
                    defaultBranchRef {
                        target {
                            ... on Commit {
                                history(since: $since, until: $until, author: {}) {
                                    edges {
                                        node {
                                            message
                                            committedDate
                                            url
                                            author {
                                                name
                                                email
                                                user {
                                                    login
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
            
            variables = {
                "owner": owner,
                "repo": repo,
                "since": today_start,
                "until": today_end
            }
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.graphql_url,
                        headers=self.headers,
                        json={"query": query, "variables": variables}
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    if "errors" in data:
                        logger.error(f"GraphQL errors when fetching commits: {data['errors']}")
                        continue
                    
                    # Extract commit data
                    commit_edges = data.get("data", {}).get("repository", {}).get("defaultBranchRef", {})
                    if not commit_edges:
                        logger.info(f"No default branch found for {owner}/{repo}")
                        continue
                    
                    target = commit_edges.get("target", {})
                    if not target:
                        logger.info(f"No target found for {owner}/{repo}")
                        continue
                    
                    history = target.get("history", {})
                    if not history:
                        logger.info(f"No history found for {owner}/{repo}")
                        continue
                    
                    edges = history.get("edges", [])
                    
                    for edge in edges:
                        node = edge.get("node", {})
                        commit_data = {
                            "repo": repo,
                            "message": node.get("message", ""),
                            "date": node.get("committedDate", ""),
                            "url": node.get("url", ""),
                            "author": {
                                "name": node.get("author", {}).get("name", ""),
                                "email": node.get("author", {}).get("email", ""),
                                "username": node.get("author", {}).get("user", {}).get("login", "")
                            }
                        }
                        all_commits.append(commit_data)
            
            except Exception as e:
                logger.error(f"Error retrieving commits for {owner}/{repo}: {e}")
                continue
                
        logger.info(f"Found {len(all_commits)} commits for today")
        return all_commits
    
    async def _get_user_repositories(self, username: str) -> List[str]:

        query = """
        query($username: String!, $first: Int!) {
            user(login: $username) {
                repositories(first: $first, ownerAffiliations: OWNER) {
                    nodes {
                        name
                    }
                }
            }
        }
        """
        
        variables = {
            "username": username,
            "first": 100  # Limit to first 100 repositories
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.graphql_url,
                    headers=self.headers,
                    json={"query": query, "variables": variables}
                )
                response.raise_for_status()
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL errors when fetching repositories: {data['errors']}")
                    return []
                
                repos = [repo["name"] for repo in data["data"]["user"]["repositories"]["nodes"]]
                logger.info(f"Found {len(repos)} repositories for user {username}")
                return repos
                
        except Exception as e:
            logger.error(f"Error retrieving repositories: {e}")
            return []

async def fetch_github_activity():
    try:
        github_client = GitHubClient()
        tasks = await github_client.get_tasks_for_today()
        commits = await github_client.get_commits_for_today()
        logger.info(f"Found {len(tasks)} tasks and {len(commits)} commits for today")
        return tasks, commits
    except Exception as e:
        logger.error(f"Error fetching GitHub activity: {e}")
        return [], []  # Return empty lists instead of failing
