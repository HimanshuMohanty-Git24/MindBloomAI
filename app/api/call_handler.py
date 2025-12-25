from fastapi import APIRouter, WebSocket, HTTPException, Depends, Request, Response, BackgroundTasks
from ..services.twilio_service import TwilioService
from ..services.sarvam_service import SarvamAIService
from ..services.email_service import email_service
from ..services.intelligence_service import IntelligenceService
from ..utils import audio_utils
import base64
import json
from typing import Dict, List, Optional
from twilio.twiml.voice_response import VoiceResponse, Connect, Start
import logging
import asyncio
import time
import re

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

router = APIRouter()
twilio_service = TwilioService()
sarvam_service = SarvamAIService()

# Store active WebSocket connections and their state
active_connections: Dict[str, WebSocket] = {}
audio_buffers: Dict[str, List[bytes]] = {}
processing_locks: Dict[str, bool] = {}
background_tasks: Dict[str, asyncio.Task] = {}
speech_states: Dict[str, dict] = {}  # Track speech state for each connection

# Session tracking for email follow-ups
session_data: Dict[str, dict] = {}  # Stores: phone, email, topics, mood, crisis_detected

# Constants for audio processing
MIN_SPEECH_DURATION_MS = 1000  # Minimum speech duration (1 second)
MAX_SPEECH_DURATION_MS = 15000  # Maximum speech duration (15 seconds)
SILENCE_DURATION_MS = 1000  # Duration of silence to mark end of speech

def should_process_speech(connection_id: str) -> bool:
    """Determine if we should process the current speech buffer"""
    state = speech_states.get(connection_id, {})
    if not state:
        return False
    
    current_time = time.time() * 1000
    speech_start = state.get('speech_start', current_time)
    last_speech = state.get('last_speech', current_time)
    
    # Calculate durations
    speech_duration = current_time - speech_start
    silence_duration = current_time - last_speech
    
    # Process if:
    # 1. We have enough silence after speech
    # 2. OR we've reached maximum duration
    if speech_duration >= MIN_SPEECH_DURATION_MS:
        if silence_duration >= SILENCE_DURATION_MS or speech_duration >= MAX_SPEECH_DURATION_MS:
            logger.info(f"Processing speech: duration={speech_duration}ms, silence={silence_duration}ms")
            return True
    
    return False

async def process_audio(websocket: WebSocket, connection_id: str, media_data: dict):
    """Process audio in background task"""
    if processing_locks.get(connection_id, False):
        logger.debug("Already processing audio for this connection")
        return
        
    try:
        processing_locks[connection_id] = True
        buffer = audio_buffers[connection_id]
        
        if not buffer:
            return
            
        duration_ms = audio_utils.get_audio_duration_ms(buffer)
        if duration_ms < MIN_SPEECH_DURATION_MS:
            return
            
        logger.info(f"Processing audio buffer of duration {duration_ms}ms")
        
        try:
            # Convert to WAV
            wav_data = audio_utils.convert_audio(buffer)
            
            # Removed file writing for latency improvement
            
            # Clear buffer and reset speech state
            audio_buffers[connection_id] = []
            speech_states[connection_id] = {}
            
            # Process audio through Sarvam AI
            logger.info("Starting speech-to-text translation")
            english_text, original_language = await sarvam_service.transcribe_and_translate_audio(
                audio_data=wav_data
            )
            
            if english_text and len(english_text.strip()) > 0:
                logger.info(f"Speech translated to English: '{english_text}', Original language: {original_language}")
                
                # Default to English if language detection failed
                if original_language is None:
                    original_language = "en-IN"
                
                # Initialize session data if not exists
                if connection_id not in session_data:
                    session_data[connection_id] = {
                        "phone": "Unknown",
                        "email": None,
                        "name": "Friend",
                        "topics": [],
                        "mood": "neutral",
                        "crisis_detected": False,
                        "awaiting_email": False,        # True when we've asked for email
                        "nudged_appointment": False,    # True when we've suggested appointment
                        "interaction_count": 0          # Track conversation turns
                    }
                
                # Initialize flags
                is_farewell = False
                is_breathing_request = False
                
                # ============ 1. CRISIS DETECTION ============
                is_crisis = IntelligenceService.detect_crisis(english_text)
                if is_crisis and not session_data[connection_id]["crisis_detected"]:
                    logger.warning(f"🚨 CRISIS DETECTED: {english_text}")
                    session_data[connection_id]["crisis_detected"] = True
                    session_data[connection_id]["topics"].append(f"Crisis: {english_text[:50]}...")
                    
                    # Send emergency email
                    phone = session_data[connection_id].get("phone", "Unknown")
                    asyncio.create_task(asyncio.to_thread(
                        email_service.send_crisis_alert, phone, english_text
                    ))
                    logger.info("Emergency email alert sent")
                    
                    # Compassionate crisis response
                    english_response = "I hear you, and I want you to know that you matter. What you're feeling right now is temporary, even though it doesn't feel that way. Please, let's talk. If things feel too overwhelming, please reach out to iCALL at 9152987821 or Vandrevala Foundation at 1860-2662-345. I'm here with you right now."
                    logger.info("Crisis response generated")
                
                # ============ 2. MOOD DETECTION ============
                elif not is_crisis:
                    detected_mood = IntelligenceService.detect_mood(english_text)
                    if detected_mood != "neutral":
                        session_data[connection_id]["mood"] = detected_mood
                        logger.info(f"Mood detected: {detected_mood}")
                    
                    # Increment interaction count for nudge timing
                    session_data[connection_id]["interaction_count"] = session_data[connection_id].get("interaction_count", 0) + 1
                    interaction_count = session_data[connection_id]["interaction_count"]
                    logger.info(f"Interaction count: {interaction_count}")
                    
                    # ============ 3. BREATHING EXERCISE REQUEST ============
                    if IntelligenceService.detect_breathing_request(english_text):
                        is_breathing_request = True  # Flag for audio playback later
                        logger.info("Breathing exercise requested - will play audio after intro")
                        english_response = "Of course, let's do a calming breathing exercise together. Get comfortable, close your eyes if you like, and follow along with this one-minute guided breathing."
                        session_data[connection_id]["topics"].append("Breathing exercise")
                    
                    # ============ 4. AWAITING EMAIL STATE - User was asked for email ============
                    elif session_data[connection_id].get("awaiting_email", False):
                        user_email = IntelligenceService.extract_email(english_text)
                        if user_email:
                            # Email provided - process booking
                            session_data[connection_id]["email"] = user_email
                            session_data[connection_id]["awaiting_email"] = False
                            logger.info(f"User email collected (awaiting state): {user_email}")
                            
                            # Send booking link
                            user_name = session_data[connection_id].get("name", "Friend")
                            asyncio.create_task(asyncio.to_thread(
                                email_service.send_appointment_booking_link, user_email, user_name
                            ))
                            
                            # Spell out email for confirmation
                            spelled_email = " ".join(list(user_email.replace("@", " at ").replace(".", " dot ")))
                            english_response = f"Perfect! I've sent the appointment booking link to {spelled_email}. You'll receive it shortly. Our team will get back to you within 24 hours. Is there anything else you'd like to talk about?"
                            session_data[connection_id]["topics"].append("Appointment booking completed")
                        else:
                            # No email detected - prompt again
                            logger.info("No email detected while awaiting - prompting again")
                            english_response = "I didn't quite catch that email address. Could you please share your email address again? For example, yourname at gmail dot com."
                    
                    # ============ 5. NUDGED APPOINTMENT - Check for yes/no response ============
                    elif session_data[connection_id].get("nudged_appointment", False):
                        if IntelligenceService.detect_confirmation(english_text):
                            # User confirmed - ask for email
                            logger.info("User confirmed appointment suggestion")
                            session_data[connection_id]["nudged_appointment"] = False
                            session_data[connection_id]["awaiting_email"] = True
                            english_response = "That's wonderful! Taking this step shows real strength. Could you please share your email address so I can send you the booking link?"
                            session_data[connection_id]["topics"].append("Appointment interest confirmed")
                        elif IntelligenceService.detect_decline(english_text):
                            # User declined - continue normal conversation
                            logger.info("User declined appointment suggestion")
                            session_data[connection_id]["nudged_appointment"] = False
                            english_response = "That's completely okay. Remember, I'm always here whenever you need to talk. Is there anything else on your mind that you'd like to share?"
                        else:
                            # Neither confirmation nor decline - pass to LLM
                            session_data[connection_id]["nudged_appointment"] = False
                            logger.info("Unclear response to nudge - passing to LLM")
                            english_response = await sarvam_service.get_groq_response(english_text, connection_id)
                    
                    # ============ 6. APPOINTMENT BOOKING REQUEST (explicit) ============
                    elif IntelligenceService.detect_booking_request(english_text):
                        logger.info("Appointment booking requested")
                        
                        if session_data[connection_id].get("email"):
                            # Already have email - send booking link
                            user_email = session_data[connection_id]["email"]
                            user_name = session_data[connection_id].get("name", "Friend")
                            asyncio.create_task(asyncio.to_thread(
                                email_service.send_appointment_booking_link, user_email, user_name
                            ))
                            english_response = f"That's a wonderful step towards your wellness journey. I've sent an appointment booking link to {user_email}. You can fill out the form, and our team will get back to you within 24 hours. Is there anything else you'd like to talk about?"
                        else:
                            # Need email - ask for it
                            session_data[connection_id]["awaiting_email"] = True
                            english_response = "I'd be happy to help you book an appointment with a professional therapist. Could you please share your email address so I can send you the booking link?"
                        session_data[connection_id]["topics"].append("Appointment booking")
                    
                    # ============ 7. EMAIL COLLECTION (spontaneous - not awaiting) ============
                    elif "@" in english_text and "." in english_text:
                        user_email = IntelligenceService.extract_email(english_text)
                        if user_email:
                            session_data[connection_id]["email"] = user_email
                            logger.info(f"User email collected (spontaneous): {user_email}")
                            
                            # If we recently nudged or user seems to want appointment, send booking link
                            # Otherwise just acknowledge and confirm
                            spelled_email = " ".join(list(user_email.replace("@", " at ").replace(".", " dot ")))
                            
                            # Send booking link since email was provided in appointment context
                            user_name = session_data[connection_id].get("name", "Friend")
                            asyncio.create_task(asyncio.to_thread(
                                email_service.send_appointment_booking_link, user_email, user_name
                            ))
                            english_response = f"Thank you! I've noted your email as {spelled_email} and sent you the therapist booking link. Is there anything else you'd like to talk about?"
                            session_data[connection_id]["topics"].append("Email collected - booking link sent")
                        else:
                            # Get response from Artika
                            logger.info("Getting response from Artika")
                            english_response = await sarvam_service.get_groq_response(english_text, connection_id)
                            logger.info(f"Artika response: '{english_response}'")
                    
                    # ============ 8. FAREWELL DETECTION ============
                    elif IntelligenceService.detect_farewell(english_text):
                        is_farewell = True
                        english_response = "Thank you so much for sharing with me today. Remember, you're stronger than you know, and I'm always here whenever you need to talk. Take care of yourself, and don't hesitate to reach out anytime. Wishing you peace and wellness. Goodbye!"
                        logger.info("Farewell detected - sending closing message")
                        
                        # Send session summary email if we have their email
                        if session_data[connection_id].get("email"):
                            user_email = session_data[connection_id]["email"]
                            user_name = session_data[connection_id].get("name", "Friend")
                            topics = session_data[connection_id].get("topics", [])
                            mood = session_data[connection_id].get("mood", "neutral")
                            asyncio.create_task(asyncio.to_thread(
                                email_service.send_session_summary, user_email, user_name, topics, mood
                            ))
                            logger.info(f"Session summary email will be sent to {user_email}")
                    
                    # ============ 9. NORMAL CONVERSATION ============
                    else:
                        is_farewell = False
                        # Track topic
                        if len(english_text) > 10:
                            session_data[connection_id]["topics"].append(english_text[:50])
                        
                        # Get response from Artika (with conversation memory)
                        logger.info("Getting response from Artika")
                        english_response = await sarvam_service.get_groq_response(english_text, connection_id)
                        logger.info(f"Artika response: '{english_response}'")
                        
                        # Check if the AI response suggested an appointment
                        # Mark as nudged if the response mentions booking/appointment/therapist
                        appointment_nudge_indicators = ["booking link", "professional therapist", "connect with a professional", "book an appointment", "schedule a session"]
                        if any(indicator in english_response.lower() for indicator in appointment_nudge_indicators):
                            session_data[connection_id]["nudged_appointment"] = True
                            logger.info("Appointment nudge detected in AI response - setting nudged_appointment flag")
                
                # Translate response if not English
                if original_language != "en-IN":
                    logger.info(f"Translating response to {original_language}")
                    translated_response = await sarvam_service.translate_text(
                        input_text=english_response,
                        target_language=original_language,
                        source_language="en-IN"
                    )
                    logger.info(f"Translated response: '{translated_response}'")
                else:
                    translated_response = english_response
                
                # Convert to speech
                logger.info("Converting response to speech")
                response_audio = await sarvam_service.text_to_speech(
                    text=translated_response,
                    target_language=original_language
                )
                
                if response_audio and websocket in active_connections.values():
                    try:
                        # Decode base64 audio
                        wav_bytes = base64.b64decode(response_audio)
                        
                        # Removed response file writing for latency improvement
                        
                        # Convert to mu-law format for Twilio
                        mu_law_audio = audio_utils.convert_to_mulaw(wav_bytes)
                        
                        # Removed mu-law file writing for latency improvement
                        
                        # Encode mu-law audio to base64 for Twilio
                        response_payload = base64.b64encode(mu_law_audio).decode('utf-8')
                        
                        # Send audio response in chunks to avoid buffer overflow
                        chunk_size = 640  # 20ms chunks at 8kHz
                        for i in range(0, len(mu_law_audio), chunk_size):
                            chunk = mu_law_audio[i:i + chunk_size]
                            chunk_payload = base64.b64encode(chunk).decode('utf-8')
                            
                            # Send chunk to Twilio
                            await websocket.send_text(json.dumps({
                                "event": "media",
                                "streamSid": media_data["streamSid"],
                                "media": {
                                    "payload": chunk_payload
                                }
                            }))
                            
                            # Small delay between chunks
                            await asyncio.sleep(0.02)  # 20ms delay between chunks
                            
                        logger.info("Audio response sent successfully in chunks")
                        
                        # If this was a farewell, close the call after audio finishes
                        if is_farewell:
                            # Calculate audio duration: mu-law is 8000 samples/sec, 1 byte per sample
                            audio_duration_seconds = len(mu_law_audio) / 8000
                            wait_time = audio_duration_seconds + 2  # Add 2 seconds buffer
                            logger.info(f"Farewell message sent ({audio_duration_seconds:.1f}s) - waiting {wait_time:.1f}s before ending call")
                            await asyncio.sleep(wait_time)
                            await websocket.close()
                            return  # Exit the process_audio function
                        
                        # If breathing exercise was requested, play the breathing audio
                        if is_breathing_request:
                            logger.info("Playing breathing exercise audio...")
                            breathing_audio = audio_utils.load_breathing_audio()
                            if breathing_audio:
                                # Send breathing audio in chunks
                                chunk_size = 640
                                for i in range(0, len(breathing_audio), chunk_size):
                                    chunk = breathing_audio[i:i + chunk_size]
                                    chunk_payload = base64.b64encode(chunk).decode('utf-8')
                                    await websocket.send_text(json.dumps({
                                        "event": "media",
                                        "streamSid": media_data["streamSid"],
                                        "media": {
                                            "payload": chunk_payload
                                        }
                                    }))
                                    await asyncio.sleep(0.02)
                                logger.info("Breathing audio sent successfully")
                                
                                # No need to wait - Twilio queues audio and plays sequentially
                                # Send follow-up message immediately (it will play after breathing audio)
                                followup_text = "Take a moment to notice how you feel now. Your body and mind have had a chance to reset. How are you feeling?"
                                logger.info("Sending breathing follow-up message")
                                followup_audio = await sarvam_service.text_to_speech(
                                    text=followup_text,
                                    target_language=original_language
                                )
                                if followup_audio:
                                    followup_wav = base64.b64decode(followup_audio)
                                    followup_mulaw = audio_utils.convert_to_mulaw(followup_wav)
                                    for i in range(0, len(followup_mulaw), chunk_size):
                                        chunk = followup_mulaw[i:i + chunk_size]
                                        chunk_payload = base64.b64encode(chunk).decode('utf-8')
                                        await websocket.send_text(json.dumps({
                                            "event": "media",
                                            "streamSid": media_data["streamSid"],
                                            "media": {"payload": chunk_payload}
                                        }))
                                        await asyncio.sleep(0.02)
                                    logger.info("Breathing follow-up sent")
                            else:
                                logger.error("Could not load breathing audio file")
                        
                    except Exception as e:
                        logger.error(f"Error handling response audio: {e}")
                else:
                    logger.error("No response audio generated or websocket disconnected")
            else:
                logger.info("No speech detected in audio")
        
        except Exception as e:
            logger.error(f"Error processing audio chunk: {str(e)}")
            # Don't clear buffer on error unless it's too long
            if duration_ms >= MAX_SPEECH_DURATION_MS:
                audio_buffers[connection_id] = []
                speech_states[connection_id] = {}
    
    except Exception as e:
        logger.error(f"Error in process_audio: {e}")
    
    finally:
        processing_locks[connection_id] = False

@router.websocket("/ws/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connection for media streaming"""
    connection_id = str(id(websocket))
    logger.info(f"New WebSocket connection: {connection_id}")
    
    await websocket.accept()
    logger.info(f"WebSocket connection accepted: {connection_id}")
    
    try:
        # Initialize connection state
        active_connections[connection_id] = websocket
        audio_buffers[connection_id] = []
        processing_locks[connection_id] = False
        speech_states[connection_id] = {}
        
        while True:
            # Receive audio data from Twilio
            data = await websocket.receive_text()
            media_data = json.loads(data)
            
            if media_data.get("event") == "media":
                # Process audio chunk
                audio_data = base64.b64decode(media_data["media"]["payload"])
                current_time = time.time() * 1000
                
                # Update speech state based on silence detection
                is_silent = audio_utils.is_silence(audio_data)
                state = speech_states.get(connection_id, {})
                
                if not is_silent:
                    # Speech detected
                    if not state:
                        # Start of new speech
                        state = {
                            'speech_start': current_time,
                            'last_speech': current_time
                        }
                    else:
                        # Continue speech
                        state['last_speech'] = current_time
                    speech_states[connection_id] = state
                    
                    # Add audio to buffer
                    audio_buffers[connection_id].append(audio_data)
                    
                    # Check if we should process (max duration reached)
                    if should_process_speech(connection_id):
                        await process_audio(websocket, connection_id, media_data)
                else:
                    # Silence detected
                    if state:
                        # Add silence to buffer
                        audio_buffers[connection_id].append(audio_data)
                        
                        # Check if we should process (enough silence after speech)
                        if should_process_speech(connection_id):
                            await process_audio(websocket, connection_id, media_data)
                
            elif media_data.get("event") == "start":
                logger.info("Media stream started")
                # Extract caller info from start event
                start_data = media_data.get("start", {})
                custom_params = start_data.get("customParameters", {})
                caller_phone = custom_params.get("from", "Unknown")
                
                # Also check streamSid if available
                stream_sid = start_data.get("streamSid", "")
                
                # Initialize session data with caller phone
                if connection_id not in session_data:
                    session_data[connection_id] = {
                        "phone": caller_phone,
                        "email": None,
                        "name": "Friend",
                        "topics": [],
                        "mood": "neutral",
                        "crisis_detected": False,
                        "stream_sid": stream_sid,
                        "awaiting_email": False,
                        "nudged_appointment": False,
                        "interaction_count": 0
                    }
                else:
                    session_data[connection_id]["phone"] = caller_phone
                    session_data[connection_id]["stream_sid"] = stream_sid
                
                logger.info(f"Caller phone captured: {caller_phone}")
            elif media_data.get("event") == "stop":
                logger.info("Media stream stopped")
                # Process any remaining audio
                if audio_buffers[connection_id]:
                    await process_audio(websocket, connection_id, media_data)
            elif media_data.get("event") == "mark":
                logger.info(f"Received mark event: {media_data.get('type')}")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    
    finally:
        # Clean up connection
        if connection_id in active_connections:
            del active_connections[connection_id]
        if connection_id in audio_buffers:
            del audio_buffers[connection_id]
        if connection_id in processing_locks:
            del processing_locks[connection_id]
        if connection_id in speech_states:
            del speech_states[connection_id]
        if connection_id in background_tasks:
            task = background_tasks[connection_id]
            if not task.done():
                task.cancel()
            del background_tasks[connection_id]
        # Clear conversation memory for this connection
        sarvam_service.clear_conversation_history(connection_id)
        # Clear session data
        if connection_id in session_data:
            del session_data[connection_id]
        logger.info(f"WebSocket connection closed and cleaned up: {connection_id}")
        try:
            await websocket.close()
        except:
            pass

@router.post("/voice")
@router.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming Twilio calls with TwiML response"""
    try:
        logger.info("Incoming call received")
        form_data = await request.form()
        
        # Get call information
        from_number = form_data.get('From', 'Unknown')
        from_city = form_data.get('FromCity', 'Unknown City')
        logger.info(f"Call from {from_number} in {from_city}")
        
        # Create TwiML response
        response = VoiceResponse()
        
        # Add initial greeting for MindBloom AI
        response.say("Welcome to MindBloom AI. I'm Artika, your mental wellness companion. I'm here to listen and support you. Please feel free to share what's on your mind in any language.")
        
        # Use Connect with Stream for true bidirectional audio
        # Connect verb allows both receiving and sending audio through WebSocket
        connect = Connect()
        stream = connect.stream(
            url=f"wss://{request.headers.get('host')}/ws/media-stream"
        )
        # Pass caller phone number as custom parameter
        stream.parameter(name="from", value=from_number)
        response.append(connect)
        
        logger.info("Generated TwiML response")
        logger.debug(f"TwiML: {str(response)}")
        
        # Return TwiML response
        return Response(content=str(response), media_type="application/xml")
    
    except Exception as e:
        logger.error(f"Error handling incoming call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/outbound-call")
async def create_outbound_call(call_data: dict):
    """Create an outbound call"""
    try:
        logger.info(f"Creating outbound call: {call_data}")
        call = twilio_service.create_call(
            to_number=call_data["to"],
            webhook_url=call_data["webhook_url"],
            from_number=call_data.get("from")  # Optional from_number
        )
        logger.info(f"Outbound call created successfully: {call.sid}")
        return {"call_sid": call.sid}
    except Exception as e:
        logger.error(f"Error creating outbound call: {e}")
        raise HTTPException(status_code=500, detail=str(e))
