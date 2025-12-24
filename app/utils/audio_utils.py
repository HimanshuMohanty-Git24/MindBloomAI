import audioop
import wave
import io
import os
import logging

# Constants for audio processing
SILENCE_THRESHOLD = 1000  # Increased threshold to be safer (approx -40dBfs)
# RMS ranges from 0 to 32767 for 16-bit audio
# 200 was very low. 1000 is still low but maybe better.

SAMPLES_PER_MS = 8  # At 8kHz sample rate

logger = logging.getLogger(__name__)

def is_silence(audio_data: bytes) -> bool:
    """Check if audio chunk is silence"""
    try:
        # audioop.ulaw2lin returns 2-byte (16-bit) width linear PCM data
        pcm_data = audioop.ulaw2lin(audio_data, 2)
        rms = audioop.rms(pcm_data, 2)
        # logger.debug(f"Audio RMS: {rms}")
        return rms < SILENCE_THRESHOLD
    except Exception as e:
        logger.error(f"Error checking silence: {e}")
        return True

def get_audio_duration_ms(audio_data: list[bytes]) -> float:
    """Calculate duration of audio in milliseconds"""
    # Each byte in mu-law is one sample.
    # 8000 samples per second.
    # So 8 bytes = 1 ms.
    total_bytes = sum(len(chunk) for chunk in audio_data)

    # Original code was: (total_bytes / 2) / SAMPLES_PER_MS
    # This implies 2 bytes per sample, but mu-law is 1 byte per sample.
    # If the input `audio_data` is a list of mu-law encoded bytes, then it should be:
    # total_bytes / SAMPLES_PER_MS

    # However, keeping backward compatibility with what I think was the intention
    # (maybe they were treating it as if it was converted to 16-bit already? No, it's passed directly from buffer)
    # The buffer stores what comes from Twilio, which is base64 decoded payload.
    # Twilio sends mu-law (PCMU) which is 8-bit.

    return total_bytes / SAMPLES_PER_MS

def convert_audio(audio_data: list[bytes]) -> bytes:
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

def load_breathing_audio() -> bytes | None:
    """Load and convert breathing exercise MP3 to mu-law format"""
    try:
        import subprocess

        # Determine the path relative to the project root
        # This assumes this file is in app/utils/
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        breathing_file = os.path.join(project_root, "assets", "Inhale.mp3")

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
