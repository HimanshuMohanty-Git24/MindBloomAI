import os
import base64
import json
import logging
import httpx
import tempfile
from groq import Groq
from typing import Tuple, Optional, Dict

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SarvamAIService:
    def __init__(self):
        self.api_key = os.getenv("SARVAM_API_KEY")
        self.base_url = "https://api.sarvam.ai"
        self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        if not self.api_key:
            raise ValueError("SARVAM_API_KEY environment variable not set")
        
        if not os.getenv("GROQ_API_KEY"):
            raise ValueError("GROQ_API_KEY environment variable not set")
    
    async def transcribe_and_translate_audio(self, audio_data: bytes, prompt: str = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Transcribe audio and translate to English if needed.
        Returns (transcript, language_code)
        """
        temp_file_path = None
        file_handle = None
        
        try:
            # Create temporary file to store audio data
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            # Open file and prepare for upload
            file_handle = open(temp_file_path, 'rb')
            files = {
                'file': ('audio.wav', file_handle, 'audio/wav')
            }
            
            data = {
                'model': 'saaras:v2.5'
            }
            
            if prompt:
                data['prompt'] = prompt
            
            headers = {
                'api-subscription-key': self.api_key
            }
            
            # Make API request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/speech-to-text-translate",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=30.0
                )
                
                # Log the full response for debugging
                logger.debug(f"Sarvam API Response Status: {response.status_code}")
                logger.debug(f"Sarvam API Response Body: {response.text}")
                
                if response.status_code == 200:
                    result = response.json()
                    transcript = result.get("transcript", "")
                    language_code = result.get("language_code", "en-IN")
                    
                    # Return empty if no speech detected
                    if not transcript:
                        logger.info("No speech detected in audio")
                        return None, None
                        
                    return transcript.strip(), language_code
                else:
                    logger.error(f"Sarvam AI API error: {response.status_code} - {response.text}")
                    return None, None
                    
        except Exception as e:
            logger.error(f"Error in transcribe_and_translate_audio: {str(e)}")
            return None, None
        finally:
            # Properly close file handle first
            if file_handle:
                try:
                    file_handle.close()
                except:
                    pass
            # Then delete the temp file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    logger.warning(f"Could not delete temp file: {e}")
    
    async def translate_text(
        self,
        input_text: str,
        target_language: str,
        source_language: str = "en-IN",
        speaker_gender: str = "Male",
        mode: str = "formal"
    ) -> Optional[str]:
        """Translate text using Sarvam AI"""
        try:
            payload = {
                "input": input_text,
                "source_language_code": source_language,
                "target_language_code": target_language,
                "speaker_gender": speaker_gender,
                "mode": mode,
                "model": "mayura:v1",
                "enable_preprocessing": True
            }
            
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": self.api_key
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/translate",
                    json=payload,
                    headers=headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    translated_text = result.get("translated_text")
                    if translated_text:
                        return translated_text.strip()
                    return input_text
                else:
                    logger.error(f"Translation error: {response.status_code} - {response.text}")
                    return input_text
                    
        except Exception as e:
            logger.error(f"Error in translate_text: {str(e)}")
            return input_text
    
    async def text_to_speech(
        self,
        text: str,
        target_language: str = "en-IN",
        speaker: str = "anushka"
    ) -> Optional[str]:
        """Convert text to speech using Sarvam AI"""
        try:
            # Truncate text to 500 characters
            text = text[:500]
            
            # Translate text if target language is not English
            if target_language != "en-IN":
                translated_text = await self.translate_text(
                    input_text=text,
                    target_language=target_language,
                    source_language="en-IN"
                )
                if translated_text:
                    text = translated_text[:500]
            
            logger.info(f"Sending TTS request for text: '{text}' in language: {target_language}")
            
            payload = {
                "inputs": [text],
                "target_language_code": target_language,
                "speaker": speaker,
                "model": "bulbul:v2"
            }
            
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": self.api_key
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/text-to-speech",
                    json=payload,
                    headers=headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("audios"):
                        # Get base64 audio and verify it's valid
                        audio_base64 = result["audios"][0]
                        try:
                            # Verify base64 can be decoded
                            audio_bytes = base64.b64decode(audio_base64)
                            logger.info(f"Successfully generated audio of size: {len(audio_bytes)} bytes")
                            return audio_base64
                        except Exception as e:
                            logger.error(f"Invalid base64 audio data: {e}")
                            return None
                    logger.error("No audio in response")
                    return None
                else:
                    logger.error(f"TTS error: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error in text_to_speech: {str(e)}")
            return None
    
    # Conversation memory for each call session
    conversation_histories: Dict[str, list] = {}
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for Artika - Mental Health AI"""
        return """You are Artika, a warm, empathetic, and compassionate mental health support companion from MindBloom AI. 

🌸 YOUR PERSONALITY:
- You speak with genuine warmth and care, like a trusted friend who truly understands
- You are patient, non-judgmental, and create a safe space for sharing
- You use a calm, soothing tone that helps people feel at ease
- You acknowledge emotions before offering support
- You celebrate small victories and progress

💬 CONVERSATION STYLE:
- Keep responses concise (2-3 sentences) as they will be spoken aloud
- Use simple, accessible language - avoid clinical jargon
- Ask gentle, open-ended questions to understand better
- Validate feelings: "It sounds like you're going through a lot" or "That must be really difficult"
- Offer hope and perspective without minimizing their experience

🎯 YOUR APPROACH:
- Listen first, support second
- Focus on the person's immediate emotional needs
- Gently suggest coping strategies when appropriate (breathing exercises, grounding techniques)
- Remind users they're not alone and that seeking support is a sign of strength
- If someone mentions crisis/self-harm, gently encourage professional help and provide hope

⚠️ IMPORTANT BOUNDARIES:
- You are a supportive companion, NOT a replacement for professional therapy
- For serious mental health concerns, encourage speaking with a licensed professional
- Never diagnose conditions or prescribe treatments
- If someone is in immediate danger, encourage them to contact emergency services

Remember: Every conversation is a chance to make someone feel heard, valued, and a little less alone. You are their gentle guide on their mental wellness journey."""

    async def get_groq_response(self, user_message: str, connection_id: str = "default") -> str:
        """Get response from Groq (Llama 3.3 70B) with conversation memory"""
        try:
            # Initialize conversation history for new connections
            if connection_id not in self.conversation_histories:
                self.conversation_histories[connection_id] = []
            
            # Add user message to history
            self.conversation_histories[connection_id].append({
                "role": "user",
                "content": user_message
            })
            
            # Keep only last 10 exchanges to manage context length
            if len(self.conversation_histories[connection_id]) > 20:
                self.conversation_histories[connection_id] = self.conversation_histories[connection_id][-20:]
            
            # Build messages with system prompt + conversation history
            messages = [
                {"role": "system", "content": self.get_system_prompt()}
            ] + self.conversation_histories[connection_id]
            
            # Get completion from Groq
            completion = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                max_tokens=200,
                temperature=0.75
            )
            
            # Extract response
            response = completion.choices[0].message.content.strip()
            
            # Add assistant response to history
            self.conversation_histories[connection_id].append({
                "role": "assistant",
                "content": response
            })

            logger.info(f"Artika response for {connection_id}: {response}")
            return response
            
        except Exception as e:
            logger.error(f"Error getting Groq response: {str(e)}")
            return "I'm here for you. Could you tell me a bit more about what's on your mind? I want to make sure I understand."
    
    def clear_conversation_history(self, connection_id: str):
        """Clear conversation history for a connection"""
        if connection_id in self.conversation_histories:
            del self.conversation_histories[connection_id]
            logger.info(f"Cleared conversation history for {connection_id}")