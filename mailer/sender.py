import os
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from datetime import datetime

from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class EmailSender:
    """Class for sending emails via SMTP."""
    
    def __init__(self):
        """Initialize the EmailSender with credentials from environment variables."""
        self.smtp_server = os.getenv("SMTP_SERVER",'smtp.gmail.com')
        self.smtp_port = int(os.getenv("SMTP_PORT", 465))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.sender_email = os.getenv("SENDER_EMAIL", self.smtp_user)
        self.use_ssl = os.getenv("SMTP_USE_SSL", "true").lower() == "true"
        
        # Verify credentials are available
        if not all([self.smtp_server, self.smtp_port, self.smtp_user, self.smtp_password]):
            raise ValueError("Missing SMTP configuration in environment variables")
        
    def send_email(self, recipient_emails: List[str], subject: str, body: str, 
                   is_html: bool = False) -> bool:
        """
        Send an email to one or more recipients.
        
        Args:
            recipient_emails: List of email addresses to send to
            subject: Email subject line
            body: Email body content
            is_html: If True, the body is treated as HTML, otherwise as plain text
            
        Returns:
            True if the email was sent successfully, False otherwise
        """
        try:
            # Create message
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = ", ".join(recipient_emails)
            msg["Subject"] = subject
            
            # Attach body with appropriate content type
            content_type = "html" if is_html else "plain"
            msg.attach(MIMEText(body, content_type))
            
            # Connect to SMTP server and send
            if self.use_ssl:
                # Use SSL (port 465)
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                # Use STARTTLS (port 587)
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
                
            logger.info(f"Email sent successfully to {', '.join(recipient_emails)}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    def send_report(self, recipient_emails: List[str], report: str, date: Optional[datetime] = None) -> bool:
        """
        Send a productivity report via email.
        
        Args:
            recipient_emails: List of email addresses to send the report to
            report: The generated report content
            date: Date of the report (defaults to today)
            
        Returns:
            True if the email was sent successfully, False otherwise
        """
        if date is None:
            date = datetime.now()
            
        date_str = date.strftime("%Y-%m-%d")
        subject = f"Щоденний звіт - {date_str}"
        
        # Send the report as a simple email
        return self.send_email(recipient_emails, subject, report, is_html=False)
