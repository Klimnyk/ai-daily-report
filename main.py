import asyncio
import logging
import os
from datetime import datetime
from dotenv import load_dotenv

# Import modules for data collection
from github.client import fetch_github_activity
from clockify.client import get_formatted_today_time_entries
from report.generator import ReportGenerator
from mailer.sender import EmailSender

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def generate_daily_report():
    """
    Main function to generate a daily report:
    1. Fetches GitHub activity (tasks and commits)
    2. Fetches Clockify time entries
    3. Sends data to OpenAI for analysis and report generation
    4. Outputs the report to the console
    5. Sends the report via email to configured recipients
    """
    try:
        logger.info("Starting daily report generation process")
        
        # Step 1: Fetch data from GitHub
        logger.info("Fetching GitHub activity data...")
        tasks, commits = await fetch_github_activity()
        github_data = {
            "tasks": tasks,
            "commits": commits
        }
        
        # Step 2: Fetch data from Clockify
        logger.info("Fetching Clockify time tracking data...")
        clockify_data = await get_formatted_today_time_entries()
        # Check if Clockify data is empty - skip report generation and email sending

        if (not clockify_data or len(clockify_data) == 0) and github_data["tasks"] == 0:
            logger.info("No Clockify time entries found for today. Skipping report generation and email.")
            return None
        

        # Step 3: Generate report using OpenAI
        logger.info("Generating report using OpenAI...")
        generator = ReportGenerator()
        
        report = await generator.generate_report(
            github_data=github_data,
            clockify_data=clockify_data
        )
        
        # Step 4: Output the report to console
        logger.info("Report generated successfully")

        
        # Step 5: Send the report via email
        recipient_emails = os.getenv("RECIPIENT_EMAILS", "").split(",")
        if recipient_emails and recipient_emails[0]:
            logger.info(f"Sending report via email to {', '.join(recipient_emails)}")
            try:
                email_sender = EmailSender()
                sent = email_sender.send_report(recipient_emails, report)
                if sent:
                    logger.info("Report sent successfully via email")
                else:
                    logger.error("Failed to send report via email")
            except Exception as e:
                logger.error(f"Error sending email: {e}")
        else:
            logger.warning("No recipient emails configured, skipping email sending")
            
        return report
        
    except Exception as e:
        logger.error(f"Error generating daily report: {e}")
        return None

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(generate_daily_report())
