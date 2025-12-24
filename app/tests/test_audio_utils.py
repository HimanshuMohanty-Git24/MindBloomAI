import pytest
import audioop
import io
import wave
from app.utils.audio_utils import is_silence, get_audio_duration_ms, convert_audio, convert_to_mulaw

def test_is_silence():
    # Create silent audio data (0 values)
    silence_pcm = b'\x00\x00' * 8000
    silence_ulaw = audioop.lin2ulaw(silence_pcm, 2)
    assert is_silence(silence_ulaw) == True

    # Create loud audio data
    # Max amplitude (approx 32000)
    loud_pcm = (b'\xff\x7f' * 4000) + (b'\x00\x80' * 4000) # +32767 and -32768
    loud_ulaw = audioop.lin2ulaw(loud_pcm, 2)

    # Check RMS manually to debug
    pcm_back = audioop.ulaw2lin(loud_ulaw, 2)
    rms = audioop.rms(pcm_back, 2)
    print(f"RMS: {rms}")

    assert is_silence(loud_ulaw) == False

def test_get_audio_duration_ms():
    # 8 bytes per ms at 8kHz mulaw
    dummy_ulaw = [b'\xff' * 80] # 10 ms
    assert get_audio_duration_ms(dummy_ulaw) == 10.0

def test_convert_audio_structure():
    # Test that it produces a valid WAV file structure
    dummy_ulaw = b'\xff' * 1600 # 200 ms of audio (if 8 bytes/ms)
    wav_bytes = convert_audio([dummy_ulaw])

    with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000

def test_convert_to_mulaw():
    # Create a dummy WAV file
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 100)

    wav_data = buf.getvalue()
    ulaw = convert_to_mulaw(wav_data)
    assert len(ulaw) == 100 # 100 frames = 100 bytes in mulaw
