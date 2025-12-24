import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via Gmail SMTP"""
    
    def __init__(self):
        self.smtp_email = os.getenv("SMTP_EMAIL")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.emergency_contact = os.getenv("EMERGENCY_CONTACT_EMAIL")
        self.google_form_link = os.getenv("GOOGLE_FORM_LINK")
        
        if not self.smtp_email or not self.smtp_password:
            logger.warning("Email credentials not configured. Email features will be disabled.")
    
    def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send an email using Gmail SMTP"""
        try:
            if not self.smtp_email or not self.smtp_password:
                logger.error("Email credentials not configured")
                return False
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"MindBloom AI <{self.smtp_email}>"
            msg['To'] = to_email
            
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_email, self.smtp_password)
                server.sendmail(self.smtp_email, to_email, msg.as_string())
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False
    
    def send_crisis_alert(self, caller_phone: str, detected_text: str) -> bool:
        """Send emergency alert when crisis is detected"""
        if not self.emergency_contact:
            logger.error("Emergency contact email not configured")
            return False
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        subject = "🚨 URGENT: Crisis Alert from MindBloom AI"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #ff6b6b, #ee5a24); padding: 20px; text-align: center;">
                <h1 style="color: white; margin: 0;">🚨 Crisis Alert</h1>
            </div>
            
            <div style="padding: 30px; background: #fff5f5; border: 2px solid #ff6b6b;">
                <h2 style="color: #c0392b;">Immediate Attention Required</h2>
                
                <p><strong>A caller has expressed concerning thoughts during their conversation with Artika.</strong></p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>📞 Caller Phone:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{caller_phone}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>🕐 Time:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;">{timestamp}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd;"><strong>💬 Detected Statement:</strong></td>
                        <td style="padding: 10px; border-bottom: 1px solid #ddd; color: #c0392b;"><em>"{detected_text}"</em></td>
                    </tr>
                </table>
                
                <div style="background: #fff; padding: 15px; border-radius: 8px; margin-top: 20px;">
                    <h3 style="margin-top: 0;">Recommended Actions:</h3>
                    <ul>
                        <li>Reach out to the caller immediately</li>
                        <li>Contact local emergency services if needed</li>
                        <li>iCALL Helpline: 9152987821</li>
                        <li>Vandrevala Foundation: 1860-2662-345</li>
                    </ul>
                </div>
            </div>
            
            <div style="background: #333; color: #fff; padding: 15px; text-align: center; font-size: 12px;">
                <p>This is an automated alert from MindBloom AI - Mental Wellness Platform</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(self.emergency_contact, subject, html_body)
    
    def send_session_summary(self, user_email: str, user_name: str, topics_discussed: list, mood_detected: str) -> bool:
        """Send session summary email after call ends"""
        
        timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        topics_html = "".join([f"<li>{topic}</li>" for topic in topics_discussed]) if topics_discussed else "<li>General wellness check-in</li>"
        
        subject = "🌸 Your MindBloom AI Session Summary"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f9f9f9;">
            <div style="background: linear-gradient(135deg, #a8e6cf, #88d8b0); padding: 30px; text-align: center;">
                <h1 style="color: #2d5a4a; margin: 0;">🌸 MindBloom AI</h1>
                <p style="color: #3d7a5a; margin: 10px 0 0 0;">Your Mental Wellness Companion</p>
            </div>
            
            <div style="padding: 30px; background: #fff;">
                <h2 style="color: #2d5a4a;">Hello {user_name}! 💚</h2>
                
                <p>Thank you for taking time to care for your mental wellness today. Here's a summary of your session with Artika:</p>
                
                <div style="background: #f0fff4; padding: 20px; border-radius: 10px; margin: 20px 0;">
                    <h3 style="color: #2d5a4a; margin-top: 0;">📋 Session Details</h3>
                    <p><strong>Date:</strong> {timestamp}</p>
                    <p><strong>Mood Detected:</strong> {mood_detected}</p>
                    <p><strong>Topics Discussed:</strong></p>
                    <ul>{topics_html}</ul>
                </div>
                
                <div style="background: #fff5f0; padding: 20px; border-radius: 10px; margin: 20px 0;">
                    <h3 style="color: #e17055; margin-top: 0;">🧘 Self-Care Resources</h3>
                    <ul>
                        <li><strong>Breathing Exercise:</strong> Try 4-7-8 breathing - inhale 4 sec, hold 7 sec, exhale 8 sec</li>
                        <li><strong>Grounding Technique:</strong> Name 5 things you see, 4 you hear, 3 you touch, 2 you smell, 1 you taste</li>
                        <li><strong>Daily Affirmation:</strong> "I am worthy of peace and happiness"</li>
                    </ul>
                </div>
                
                <div style="background: #f0f4ff; padding: 20px; border-radius: 10px; margin: 20px 0;">
                    <h3 style="color: #6c5ce7; margin-top: 0;">📞 Need More Support?</h3>
                    <p>If you'd like to speak with a professional therapist, you can book an appointment:</p>
                    <a href="{self.google_form_link}" style="display: inline-block; background: #6c5ce7; color: white; padding: 12px 25px; text-decoration: none; border-radius: 25px; margin-top: 10px;">Book Therapy Session</a>
                </div>
                
                <p style="color: #666; font-style: italic;">Remember, every step you take towards your mental health is a victory. You're doing great! 🌟</p>
            </div>
            
            <div style="background: #2d5a4a; color: #fff; padding: 20px; text-align: center; font-size: 12px;">
                <p>With care,<br><strong>Artika & Team MindBloom AI</strong></p>
                <p style="opacity: 0.7;">Crisis Helpline: iCALL 9152987821 | Vandrevala 1860-2662-345</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(user_email, subject, html_body)
    
    def send_appointment_booking_link(self, user_email: str, user_name: str) -> bool:
        """Send appointment booking link to user"""
        
        subject = "📅 Book Your Therapy Session - MindBloom AI"
        
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #6c5ce7, #a29bfe); padding: 30px; text-align: center;">
                <h1 style="color: white; margin: 0;">📅 Book Your Session</h1>
            </div>
            
            <div style="padding: 30px; background: #fff;">
                <h2>Hello {user_name}! 💜</h2>
                
                <p>We're so glad you're taking this important step towards your mental wellness. Speaking with a professional can make a real difference.</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{self.google_form_link}" style="display: inline-block; background: linear-gradient(135deg, #6c5ce7, #a29bfe); color: white; padding: 15px 40px; text-decoration: none; border-radius: 30px; font-size: 18px; font-weight: bold;">
                        📝 Book Appointment Now
                    </a>
                </div>
                
                <p style="color: #666;">After you submit the form, our team will contact you within 24 hours to confirm your appointment.</p>
                
                <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-top: 20px;">
                    <p style="margin: 0;"><strong>💡 Tip:</strong> Before your session, try writing down what you'd like to discuss. It can help make the most of your time with the therapist.</p>
                </div>
            </div>
            
            <div style="background: #333; color: #fff; padding: 15px; text-align: center; font-size: 12px;">
                <p>MindBloom AI - Your Mental Wellness Journey Starts Here 🌸</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(user_email, subject, html_body)


# Global instance
email_service = EmailService()
