from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Start
import os
from dotenv import load_dotenv

load_dotenv()

class TwilioService:
    def __init__(self):
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = os.getenv("TWILIO_PHONE_NUMBER")
        
        if not self.account_sid or not self.auth_token:
            raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables are required")
        if not self.phone_number:
            raise ValueError("TWILIO_PHONE_NUMBER environment variable is required")
            
        self.client = Client(self.account_sid, self.auth_token)

    def generate_media_stream_response(self, stream_url: str) -> str:
        """Generate TwiML response for media streams"""
        response = VoiceResponse()
        
        # Configure media streams
        connect = response.connect()
        connect.stream(name='MindBloomAI-stream', url=stream_url, track='both_tracks')
        
        # Add gather for continuous speech input
        gather = response.gather(
            input='speech',
            action='/gather',
            language='en-US',
            enhanced='true',
            speech_timeout='auto'
        )
        gather.say("Please speak, and I'll respond in real-time.")
        
        return str(response)

    def create_call(self, to_number: str, webhook_url: str, from_number: str = None):
        """Create a new outbound call"""
        # Use the default Twilio phone number if no from_number is provided
        from_number = from_number or self.phone_number
        
        return self.client.calls.create(
            to=to_number,
            from_=from_number,
            url=webhook_url,
            record=True,
            twiml=self.generate_media_stream_response(webhook_url)
        )

    def end_call(self, call_sid: str):
        """End an active call"""
        call = self.client.calls(call_sid).update(status='completed')
        return call 