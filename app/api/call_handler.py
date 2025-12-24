from fastapi import APIRouter, WebSocket, HTTPException, Depends, Request, Response, BackgroundTasks
from ..services.twilio_service import TwilioService
from ..services.sarvam_service import SarvamAIService
from ..services.email_service import email_service
import base64
import json
from typing import Dict, List, Optional
from twilio.twiml.voice_response import VoiceResponse, Connect, Start
import logging
import audioop
import wave
import io
import os
from datetime import datetime
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
SILENCE_THRESHOLD = 200  # RMS threshold for silence detection
MIN_SPEECH_DURATION_MS = 1000  # Minimum speech duration (1 second)
MAX_SPEECH_DURATION_MS = 15000  # Maximum speech duration (15 seconds)
SILENCE_DURATION_MS = 1000  # Duration of silence to mark end of speech
SAMPLES_PER_MS = 8  # At 8kHz sample rate

# Crisis detection keywords - COMPREHENSIVE LIST
# Includes variations: giving/give, wanna/want, don't/do not, etc.
CRISIS_KEYWORDS = [
    # Suicide-related
    "kill myself", "killing myself", "suicide", "suicidal", "suicidal thoughts",
    "want to die", "wanna die", "wanting to die", "wish i was dead", "wish i were dead",
    "end my life", "ending my life", "end it all", "ending it all", "end everything",
    "take my life", "taking my life", "take my own life",
    
    # Not wanting to live
    "don't want to live", "do not want to live", "dont want to live",
    "don't wanna live", "dont wanna live", "no will to live",
    "can't live anymore", "cant live anymore", "cannot live anymore",
    "tired of living", "tired of life", "done with life", "done living",
    
    # Giving up
    "give up on life", "giving up on life", "given up on life",
    "give up", "giving up", "i give up", "i'm giving up", "im giving up",
    "no reason to live", "no point in living", "nothing to live for",
    "life is meaningless", "life has no meaning", "life is pointless",
    
    # Hopelessness
    "better off dead", "world is better without me", "everyone is better without me",
    "no one would miss me", "nobody would miss me", "no one cares if i die",
    "hopeless", "completely hopeless", "there's no hope", "no hope left",
    "can't go on", "cant go on", "cannot go on", "can't continue", "cant continue",
    
    # Self-harm
    "self-harm", "self harm", "selfharm", "hurt myself", "hurting myself",
    "cut myself", "cutting myself", "harm myself", "harming myself",
    "injure myself", "injuring myself", "punish myself",
    
    # Overdose / Methods
    "overdose", "take pills", "taking pills", "poison myself",
    "jump off", "jumping off", "hang myself", "hanging myself",
    
    # Life not worth it
    "life is not worth", "life isnt worth", "life isn't worth",
    "not worth living", "worthless life", "waste of life",
    "life is a burden", "burden to everyone", "burden to my family",
    
    # Single dangerous words (check carefully)
    "khatam", "marna chahta", "marna chahti", "jaan dena", "zindagi khatam"
]

# Mood detection keywords (does NOT include crisis words - those are checked first)
MOOD_KEYWORDS = {
    "anxious": ["anxious", "worried", "nervous", "panic", "stressed", "anxiety", "fear", "scared"],
    "sad": ["sad", "depressed", "lonely", "crying", "unhappy", "miserable", "grief", "down", "low"],
    "angry": ["angry", "frustrated", "irritated", "rage", "mad", "annoyed", "furious"],
    "happy": ["happy", "good", "great", "wonderful", "excited", "joyful", "grateful", "blessed"],
    "calm": ["calm", "peaceful", "relaxed", "content", "okay", "fine", "better"]
}

# Breathing exercise trigger phrases
BREATHING_TRIGGERS = [
    "breathing exercise", "help me breathe", "calm me down", "breathing",
    "can't breathe", "panic attack", "help me relax", "meditation",
    "guided breathing", "deep breath"
]

# Appointment booking trigger phrases
BOOKING_TRIGGERS = [
    "book appointment", "schedule therapy", "talk to therapist",
    "professional help", "see a counselor", "book session", "therapy appointment",
    "speak to someone", "real person", "human therapist"
]

def is_silence(audio_data: bytes) -> bool:
    """Check if audio chunk is silence"""
    try:
        pcm_data = audioop.ulaw2lin(audio_data, 2)
        rms = audioop.rms(pcm_data, 2)
        return rms < SILENCE_THRESHOLD
    except:
        return True

def get_audio_duration_ms(audio_data: List[bytes]) -> float:
    """Calculate duration of audio in milliseconds"""
    total_bytes = sum(len(chunk) for chunk in audio_data)
    return (total_bytes / 2) / SAMPLES_PER_MS

def convert_audio(audio_data: List[bytes]) -> bytes:
    """Convert mu-law audio chunks to WAV format at 16kHz for Sarvam AI"""
    try:
        # Convert mu-law to linear PCM
        pcm_data = b''.join([audioop.ulaw2lin(chunk, 2) for chunk in audio_data])
        
        # Resample from 8kHz to 16kHz for Sarvam AI compatibility
        pcm_data_16k, _ = audioop.ratecv(pcm_data, 2, 1, 8000, 16000, None)
        
        # Create WAV file in memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes per sample
            wav_file.setframerate(16000)  # 16kHz sample rate for Sarvam AI
            wav_file.writeframes(pcm_data_16k)
        
        return wav_buffer.getvalue()
    except Exception as e:
        logger.error(f"Error converting audio: {e}")
        raise

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

def convert_to_mulaw(wav_data: bytes) -> bytes:
    """Convert WAV audio to mu-law format for Twilio"""
    try:
        # Read WAV data
        with wave.open(io.BytesIO(wav_data), 'rb') as wav_file:
            # Read wav file parameters
            n_channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            # Read PCM data
            pcm_data = wav_file.readframes(wav_file.getnframes())

        # Convert to mono if needed
        if n_channels == 2:
            pcm_data = audioop.tomono(pcm_data, sampwidth, 1, 1)

        # Convert to 16-bit if needed
        if sampwidth != 2:
            pcm_data = audioop.lin2lin(pcm_data, sampwidth, 2)

        # Resample to 8kHz if needed
        if framerate != 8000:
            pcm_data = audioop.ratecv(pcm_data, 2, 1, framerate, 8000, None)[0]

        # Convert to mu-law
        mu_law_data = audioop.lin2ulaw(pcm_data, 2)
        return mu_law_data
    except Exception as e:
        logger.error(f"Error converting to mu-law: {e}")
        raise

def load_breathing_audio() -> bytes:
    """Load and convert breathing exercise MP3 to mu-law format"""
    try:
        import subprocess
        
        breathing_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "Inhale.mp3")
        
        if not os.path.exists(breathing_file):
            logger.error(f"Breathing audio file not found: {breathing_file}")
            return None
        
        # Use ffmpeg to convert MP3 to WAV (8kHz, mono, 16-bit)
        # ffmpeg needs to be installed on the system
        temp_wav = os.path.join(os.path.dirname(breathing_file), "breathing_temp.wav")
        
        result = subprocess.run([
            "ffmpeg", "-y", "-i", breathing_file,
            "-ar", "8000", "-ac", "1", "-sample_fmt", "s16",
            temp_wav
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"ffmpeg error: {result.stderr}")
            return None
        
        # Read the WAV and convert to mu-law
        with open(temp_wav, "rb") as f:
            wav_data = f.read()
        
        # Clean up temp file
        os.remove(temp_wav)
        
        # Convert to mu-law
        with wave.open(io.BytesIO(wav_data), 'rb') as wav_file:
            pcm_data = wav_file.readframes(wav_file.getnframes())
        
        mu_law_data = audioop.lin2ulaw(pcm_data, 2)
        logger.info(f"Loaded breathing audio: {len(mu_law_data)} bytes")
        return mu_law_data
        
    except Exception as e:
        logger.error(f"Error loading breathing audio: {e}")
        return None

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
            
        duration_ms = get_audio_duration_ms(buffer)
        if duration_ms < MIN_SPEECH_DURATION_MS:
            return
            
        logger.info(f"Processing audio buffer of duration {duration_ms}ms")
        
        try:
            # Convert to WAV
            wav_data = convert_audio(buffer)
            
            # Save audio file for debugging
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recordings/audio_{timestamp}_{int(duration_ms)}ms_{connection_id}.wav"
            with open(filename, "wb") as f:
                f.write(wav_data)
            logger.info(f"Saved audio file: {filename}")
            
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
                
                text_lower = english_text.lower().strip()
                
                # Initialize session data if not exists
                if connection_id not in session_data:
                    session_data[connection_id] = {
                        "phone": "Unknown",
                        "email": None,
                        "name": "Friend",
                        "topics": [],
                        "mood": "neutral",
                        "crisis_detected": False
                    }
                
                # Initialize flags
                is_farewell = False
                is_breathing_request = False
                
                # ============ 1. CRISIS DETECTION ============
                is_crisis = any(keyword in text_lower for keyword in CRISIS_KEYWORDS)
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
                    detected_mood = "neutral"
                    for mood, keywords in MOOD_KEYWORDS.items():
                        if any(kw in text_lower for kw in keywords):
                            detected_mood = mood
                            break
                    session_data[connection_id]["mood"] = detected_mood
                    logger.info(f"Mood detected: {detected_mood}")
                    
                    # ============ 3. BREATHING EXERCISE REQUEST ============
                    is_breathing_request = any(trigger in text_lower for trigger in BREATHING_TRIGGERS)
                    if is_breathing_request:
                        is_breathing_request = True  # Flag for audio playback later
                        logger.info("Breathing exercise requested - will play audio after intro")
                        english_response = "Of course, let's do a calming breathing exercise together. Get comfortable, close your eyes if you like, and follow along with this one-minute guided breathing."
                        session_data[connection_id]["topics"].append("Breathing exercise")
                    
                    # ============ 4. APPOINTMENT BOOKING REQUEST ============
                    elif any(trigger in text_lower for trigger in BOOKING_TRIGGERS):
                        logger.info("Appointment booking requested")
                        
                        if session_data[connection_id].get("email"):
                            # Send booking link
                            user_email = session_data[connection_id]["email"]
                            user_name = session_data[connection_id].get("name", "Friend")
                            asyncio.create_task(asyncio.to_thread(
                                email_service.send_appointment_booking_link, user_email, user_name
                            ))
                            english_response = f"That's a wonderful step towards your wellness journey. I've sent an appointment booking link to {user_email}. You can fill out the form, and our team will get back to you within 24 hours. Is there anything else you'd like to talk about?"
                        else:
                            english_response = "I'd be happy to help you book an appointment with a professional therapist. Could you please share your email address so I can send you the booking link?"
                        session_data[connection_id]["topics"].append("Appointment booking")
                    
                    # ============ 5. EMAIL COLLECTION ============
                    elif "@" in english_text and "." in english_text:
                        # Try to extract email from text
                        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                        email_match = re.search(email_pattern, english_text)
                        if email_match:
                            user_email = email_match.group()
                            session_data[connection_id]["email"] = user_email
                            logger.info(f"User email collected: {user_email}")
                            
                            # Spell out email letter by letter for verification
                            spelled_email = " ".join(list(user_email.replace("@", " at ").replace(".", " dot ")))
                            english_response = f"Let me confirm your email. I heard: {spelled_email}. Is that correct? If not, please spell it out letter by letter for me."
                        else:
                            # Get response from Artika
                            logger.info("Getting response from Artika")
                            english_response = await sarvam_service.get_groq_response(english_text, connection_id)
                            logger.info(f"Artika response: '{english_response}'")
                    
                    # ============ 6. FAREWELL DETECTION ============
                    elif any(phrase in text_lower for phrase in ["bye", "goodbye", "good bye", "see you", "take care", 
                        "that's all", "thats all", "i'm done", "im done", "thank you bye",
                        "thanks bye", "end call", "hang up", "gotta go", "need to go",
                        "talk later", "bye bye", "tata", "alvida", "dhanyavaad", "shukriya"]):
                        
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
                    
                    # ============ 7. NORMAL CONVERSATION ============
                    else:
                        is_farewell = False
                        # Track topic
                        if len(english_text) > 10:
                            session_data[connection_id]["topics"].append(english_text[:50])
                        
                        # Get response from Artika (with conversation memory)
                        logger.info("Getting response from Artika")
                        english_response = await sarvam_service.get_groq_response(english_text, connection_id)
                        logger.info(f"Artika response: '{english_response}'")
                
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
                        
                        # Save response WAV for debugging
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        response_filename = f"recordings/response_{timestamp}_{int(duration_ms)}ms_{connection_id}.wav"
                        with open(response_filename, "wb") as f:
                            f.write(wav_bytes)
                        logger.info(f"Saved response WAV file: {response_filename}")
                        
                        # Convert to mu-law format for Twilio
                        mu_law_audio = convert_to_mulaw(wav_bytes)
                        
                        # Save mu-law audio for debugging
                        mulaw_filename = f"recordings/response_{timestamp}_{int(duration_ms)}ms_{connection_id}.ulaw"
                        with open(mulaw_filename, "wb") as f:
                            f.write(mu_law_audio)
                        logger.info(f"Saved mu-law audio file: {mulaw_filename}")
                        
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
                            breathing_audio = load_breathing_audio()
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
                                    followup_mulaw = convert_to_mulaw(followup_wav)
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
                is_silent = is_silence(audio_data)
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
                        "stream_sid": stream_sid
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