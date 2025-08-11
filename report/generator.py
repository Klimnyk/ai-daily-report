import asyncio
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Import correctly - add sys.path modification to handle relative imports
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Add project root to sys.path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import from the new modules
from github.client import fetch_github_activity
from clockify.client import get_formatted_today_time_entries


class ReportGenerator:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided and not found in environment variables")
        
        self.api_url = "https://api.openai.com/v1/chat/completions"
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    def _load_prompt_template(self) -> str:
        """Load the prompt template from the markdown file."""
        prompt_path = Path(project_root) / "promt.md"
        system_role = Path(project_root) / "system_role.md"
        
        if not prompt_path.exists():
            logger.warning(f"Prompt template file not found: {prompt_path}")
            return ""
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            # Skip the first line which is the filepath comment
            lines = f.readlines()
            if lines and lines[0].startswith('<!-- filepath:'):
                prompt = ''.join(lines[1:])
            else:
                prompt = ''.join(lines)

        if not system_role.exists():
            logger.warning(f"System role file not found: {system_role}")
            return ""
        
        with open(system_role, 'r', encoding='utf-8') as f:
            # Skip the first line which is the filepath comment
            lines = f.readlines()
            if lines and lines[0].startswith('<!-- filepath:'):
                system_role = ''.join(lines[1:])
            else:
                system_role = ''.join(lines)                
        return prompt, system_role

    def format_github_data(self, github_data: Dict[str, Any]) -> str:
        github_text = "## GitHub Activity:\n\n"
        
        tasks = github_data.get('tasks', [])

        if tasks:
            github_text += "### Tasks:\n"
            for task in tasks:
                name = task.get('title', 'Untitled task')
                status = task.get('task_status', 'unknown')
                state = task.get('state', 'unknown')
                description = task.get('description', 'No description')
                github_text += f"- {name} ({status}, {state}): {description}\n"
            github_text += "\n"
        commits = github_data.get('commits', [])
        
        if commits:
            github_text += "### Commits:\n"
            for commit in commits:
                repo = commit.get('repo', 'unknown-repo')
                message = commit.get('message', 'No message')
                date = commit.get('date', 'Unknown date')
                github_text += f"- [{repo}] {message} ({date})\n"
            github_text += "\n"
        return github_text
    
    
    async def generate_report(self, 
                       github_data: Dict[str, Any], 
                       clockify_data: List[Dict[str, Any]]) -> str:
            
        formatted_github = self.format_github_data(github_data)
        formatted_clockify = clockify_data
        
        # Load prompt template and format with current date
        prompt_template , system_role = self._load_prompt_template()
        current_date = datetime.now().strftime('%Y-%m-%d')
        prompt = f"""
        {formatted_github}
        
        {formatted_clockify}
        
        {prompt_template.format(date=current_date)}
        """
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_role},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": float(os.getenv("OPENAI_TEMPERATURE", 0.3))
                }
                
                logger.info("Sending data to OpenAI for report generation...")
                response = await client.post(self.api_url, headers=headers, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
                    return f"Error generating report: {response.status_code} - {response.text}"
                
                response_data = response.json()

                generated_report = response_data['choices'][0]['message']['content'].strip()
                logger.info("Successfully generated productivity report")


                disclaimer = (
                    f"\n\n---\n*This report was generated using AI based on task statistics and monitoring metrics.*\n"
                    f"Model used: OpenAI {self.model}"
                )
                generated_report += disclaimer
                return generated_report
                
        except Exception as e:
            logger.error(f"Error generating report: {str(e)}")
            return f"Failed to generate report: {str(e)}"
    
    async def generate_report_from_raw_data(self, raw_data: Dict[str, Any], ) -> str:
        """
        Generate a report directly from raw data. This is a convenience method when
        data is already pre-processed elsewhere.
        
        Args:
            raw_data: Dictionary containing all necessary data already formatted
            
        Returns:
            Generated report as string
        """

        return await self.generate_report(
            github_data=raw_data.get('github_data', {}),
            clockify_data=raw_data.get('clockify_data', []),
        )


async def main():
    try:
        # Get GitHub data - unpack the tuple of tasks and commits
        tasks, commits = await fetch_github_activity()
        github_data = {
            "tasks": tasks,
            "commits": commits
        }
        
        # Get Clockify data
        clockify_data = await get_formatted_today_time_entries()
        
        generator = ReportGenerator()
        report = await generator.generate_report(
            github_data=github_data,
            clockify_data=clockify_data,
        )
        print(report)
    
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
