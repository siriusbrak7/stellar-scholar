import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import logging
from config import Config

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.config = Config()
        self.is_configured = all([self.config.MAIL_USERNAME, self.config.MAIL_PASSWORD])
    
    def send_email(self, to_email, subject, html_content, text_content=None):
        """Send email using SMTP - fails gracefully if not configured"""
        if not self.is_configured:
            logger.info(f"Email not configured. Would send to {to_email}: {subject}")
            return True  # Return True to not break workflows
        
        try:
            # Create message
            msg = MimeMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.config.MAIL_DEFAULT_SENDER
            msg['To'] = to_email
            
            # Add text/HTML parts
            if text_content:
                msg.attach(MimeText(text_content, 'plain'))
            msg.attach(MimeText(html_content, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config.MAIL_SERVER, self.config.MAIL_PORT) as server:
                if self.config.MAIL_USE_TLS:
                    server.starttls()
                server.login(self.config.MAIL_USERNAME, self.config.MAIL_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"Email sent to {to_email}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def send_assignment_reminder(self, student_email, prompt_title, due_date, student_name):
        """Send assignment due date reminder"""
        subject = f"📚 Assignment Reminder: {prompt_title}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px; }}
                .assignment-info {{ background: white; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #667eea; }}
                .due-date {{ color: #dc3545; font-weight: bold; }}
                .button {{ display: inline-block; padding: 12px 24px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎯 Stellar Scholar</h1>
                    <p>Assignment Reminder</p>
                </div>
                <div class="content">
                    <h2>Hi {student_name},</h2>
                    <p>This is a friendly reminder about your upcoming assignment:</p>
                    
                    <div class="assignment-info">
                        <h3>{prompt_title}</h3>
                        <p class="due-date">📅 Due: {due_date}</p>
                    </div>
                    
                    <p>Don't forget to submit your work before the due date!</p>
                    
                    <a href="https://stellar-scholar.onrender.com/student/dashboard" class="button">
                        Go to Dashboard
                    </a>
                    
                    <p><small>If you've already submitted this assignment, please ignore this reminder.</small></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Stellar Scholar - Assignment Reminder
        
        Hi {student_name},
        
        This is a reminder about your upcoming assignment:
        
        Assignment: {prompt_title}
        Due Date: {due_date}
        
        Please submit your work before the due date.
        
        Login to your dashboard: https://stellar-scholar.onrender.com/student/dashboard
        
        If you've already submitted this assignment, please ignore this reminder.
        """
        
        return self.send_email(student_email, subject, html_content, text_content)