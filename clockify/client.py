import os
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

CLOCKIFY_API_KEY = os.getenv("CLOCKIFY_API_KEY")
if not CLOCKIFY_API_KEY:
    raise ValueError("CLOCKIFY_API_KEY is not set in environment variables.")

BASE_URL = "https://api.clockify.me/api/v1"

HEADERS = {
    "Content-Type": "application/json",
    "X-Api-Key": CLOCKIFY_API_KEY
}

async def get_user_data() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BASE_URL}/user", headers=HEADERS)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching user data: {e.response.status_code} - {e.response.text}")
        raise
    except Exception as e:
        logger.error(f"Error fetching user data: {str(e)}")
        raise

async def get_today_time_entries() -> List[Dict[str, Any]]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today.isoformat() + "Z"  # Start of the day
    end = (today + timedelta(days=1, seconds=-1)).isoformat() + "Z"  # End of the day
    
    try:
        user_data = await get_user_data()
        workspace_id = user_data.get("defaultWorkspace")
        user_id = user_data.get("id")
        
        if not workspace_id or not user_id:
            logger.error("Failed to get workspace ID or user ID")
            return []
        
        async with httpx.AsyncClient() as client:
            url = f"{BASE_URL}/workspaces/{workspace_id}/user/{user_id}/time-entries"
            params = {
                "start": start,
                "end": end,
                "hydrated": "true"  # To get detailed information including project and task names
            }
            
            response = await client.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            time_entries = response.json()
            
            logger.info(f"Retrieved {len(time_entries)} time entries for today")
            return time_entries
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
    
    return []

def format_time_entry(entry: Dict[str, Any]) -> str:
    description = entry.get("description", "No description")
    project_name = entry.get("project", {}).get("name", "No project")
    
    start_time = entry.get("timeInterval", {}).get("start")
    end_time = entry.get("timeInterval", {}).get("end")
    duration = "In progress"
    
    if start_time and end_time:
        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        duration_seconds = (end_dt - start_dt).total_seconds()
        hours, remainder = divmod(int(duration_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration = f"{hours}h {minutes}m"
    
    return f"{description} ({project_name}) - {duration}"

async def get_formatted_today_time_entries():
    try:
        time_entries = await get_today_time_entries()
        formatted_entries = []
        logger.info(f"Retrieved {len(time_entries)} time entries")

        for entry in time_entries:
            # Handle the case when project is None
            project = entry.get("project")
            project_name = project.get("name", "No project") if project is not None else "No project"
            
            description = entry.get("description", "No description")
        
            start_time = entry.get("timeInterval", {}).get("start")
            end_time = entry.get("timeInterval", {}).get("end")
            duration_minutes = 0
            
            if start_time and end_time:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                duration_seconds = (end_dt - start_dt).total_seconds()
                duration_minutes = int(duration_seconds // 60)
            
            formatted_entries.append({
                "project_name": project_name,
                "name": description,
                "time": duration_minutes
            })
        
        logger.info(f"Formatted {len(formatted_entries)} time entries")
        if not formatted_entries:
            logger.info("No time entries found for today")
        else:
            logger.info(f"First formatted entry: {formatted_entries[0]}")
        return formatted_entries
    except Exception as e:
        logger.error(f"Error getting formatted time entries: {e}")
        return []
