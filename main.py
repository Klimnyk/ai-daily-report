"""
AI Daily Report Generator

Generates daily productivity reports by aggregating data from:
- GitLab (commits across all accessible projects)
- Jira (tasks in progress, closed today, boards)
- Clockify (time tracking entries)

Uses OpenAI to generate a human-readable report in Ukrainian.
"""

import asyncio
import logging
import os
from datetime import datetime

from dotenv import load_dotenv

# Import modules for data collection
from gitlab.client import fetch_gitlab_commits
from jira.client import fetch_jira_tasks
from clockify.client import get_formatted_today_time_entries
from report.generator import ReportGenerator
from mailer.sender import EmailSender

# Configure logging - respect LOG_LEVEL env for production
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(levelname)s - %(message)s" if log_level == "WARNING" else "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def collect_all_data() -> tuple:
    """
    Collect data from all sources concurrently.
    
    Returns:
        Tuple of (gitlab_commits, jira_data, clockify_data)
    """
    logger.info("Collecting data from all sources...")
    
    try:
        gitlab_commits, jira_data, clockify_data = await asyncio.gather(
            fetch_gitlab_commits(),
            fetch_jira_tasks(),
            get_formatted_today_time_entries(),
            return_exceptions=True
        )
        
        # Handle any exceptions from concurrent calls
        if isinstance(gitlab_commits, Exception):
            logger.error(f"Error fetching GitLab commits: {gitlab_commits}")
            gitlab_commits = []
        
        if isinstance(jira_data, Exception):
            logger.error(f"Error fetching Jira data: {jira_data}")
            jira_data = {
                "tasks_in_progress": [],
                "tasks_closed_today": [],
                "all_my_tasks": [],
                "boards": []
            }
        
        if isinstance(clockify_data, Exception):
            logger.error(f"Error fetching Clockify data: {clockify_data}")
            clockify_data = []
        
        logger.info(
            f"Data collected: {len(gitlab_commits)} commits, "
            f"{len(jira_data.get('tasks_in_progress', []))} tasks in progress, "
            f"{len(jira_data.get('tasks_closed_today', []))} tasks closed, "
            f"{len(clockify_data)} time entries"
        )
        
        return gitlab_commits, jira_data, clockify_data
        
    except Exception as e:
        logger.error(f"Error collecting data: {e}")
        return [], {"tasks_in_progress": [], "tasks_closed_today": [], "all_my_tasks": [], "boards": []}, []


def should_generate_report(
    gitlab_commits: list,
    jira_data: dict,
    clockify_data: list
) -> bool:
    """
    Check if there's enough data to generate a report.
    
    Returns:
        True if report should be generated, False otherwise
    """
    has_commits = len(gitlab_commits) > 0
    has_jira_activity = (
        len(jira_data.get("tasks_in_progress", [])) > 0 or
        len(jira_data.get("tasks_closed_today", [])) > 0
    )
    has_time_entries = len(clockify_data) > 0
    
    # Generate report if any data source has content
    # Can be configured to require Clockify entries specifically
    require_clockify = os.getenv("REQUIRE_CLOCKIFY_ENTRIES", "true").lower() == "true"
    
    if require_clockify and not has_time_entries:
        print("⏭️ SKIPPED: No Clockify time entries found for today")
        return False
    
    return has_commits or has_jira_activity or has_time_entries


async def generate_daily_report() -> str | None:
    """
    Main function to generate a daily report.
    
    Workflow:
    1. Fetches GitLab commits for today
    2. Fetches Jira tasks (in progress, closed today)
    3. Fetches Clockify time entries
    4. Generates report using OpenAI
    5. Sends the report via email
    
    Returns:
        Generated report string or None if skipped
    """
    try:
        logger.info("=" * 60)
        logger.info(f"Starting daily report generation - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        logger.info("=" * 60)
        
        # Step 1: Collect all data
        gitlab_commits, jira_data, clockify_data = await collect_all_data()
        
        # Step 2: Check if we should generate report
        if not should_generate_report(gitlab_commits, jira_data, clockify_data):
            return None
        
        # Step 3: Generate report using OpenAI
        logger.info("Generating report using OpenAI...")
        generator = ReportGenerator()
        
        report = await generator.generate_report(
            gitlab_commits=gitlab_commits,
            jira_data=jira_data,
            clockify_data=clockify_data
        )
        
        if not report or report.startswith("Error"):
            logger.error(f"Failed to generate report: {report}")
            return None
        
        logger.info("Report generated successfully")

        
        # Step 4: Send the report via email
        recipient_emails = [
            email.strip() 
            for email in os.getenv("RECIPIENT_EMAILS", "").split(",") 
            if email.strip()
        ]
        
        if recipient_emails:
            logger.info(f"Sending report via email to {len(recipient_emails)} recipient(s)")
            try:
                email_sender = EmailSender()
                sent = email_sender.send_report(recipient_emails, report)
                if sent:
                    print(f"✅ SUCCESS: Report sent to {len(recipient_emails)} recipient(s)")
                else:
                    print("❌ FAILED: Could not send email")
            except ValueError as e:
                print(f"❌ ERROR: Missing SMTP configuration")
            except Exception as e:
                print(f"❌ ERROR: Email sending failed")
        else:
            print("⚠️ WARNING: No recipient emails configured (RECIPIENT_EMAILS is empty)")
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating daily report: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Entry point for the application."""
    load_dotenv()
    
    # Validate required environment variables
    required_vars = ["OPENAI_API_KEY"]
    optional_vars = ["GITLAB_TOKEN", "JIRA_URL", "CLOCKIFY_API_KEY"]
    
    missing_required = [var for var in required_vars if not os.getenv(var)]
    if missing_required:
        logger.error(f"Missing required environment variables: {', '.join(missing_required)}")
        return
    
    missing_optional = [var for var in optional_vars if not os.getenv(var)]
    if missing_optional:
        logger.warning(f"Missing optional environment variables: {', '.join(missing_optional)}")
    
    await generate_daily_report()


if __name__ == "__main__":
    asyncio.run(main())
