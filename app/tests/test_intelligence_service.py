from app.services.intelligence_service import IntelligenceService

def test_detect_crisis():
    assert IntelligenceService.detect_crisis("I want to kill myself") == True
    assert IntelligenceService.detect_crisis("I am feeling happy") == False
    assert IntelligenceService.detect_crisis("life is meaningless") == True
    assert IntelligenceService.detect_crisis("I am tired") == False # "tired of living" is the keyword

def test_detect_mood():
    assert IntelligenceService.detect_mood("I am so anxious about the future") == "anxious"
    assert IntelligenceService.detect_mood("I feel very happy today") == "happy"
    assert IntelligenceService.detect_mood("I am angry at him") == "angry"
    assert IntelligenceService.detect_mood("I am hungry") == "neutral"

def test_detect_breathing_request():
    assert IntelligenceService.detect_breathing_request("help me breathe please") == True
    assert IntelligenceService.detect_breathing_request("I cannot breathe") == False # "can't breathe" is the trigger
    assert IntelligenceService.detect_breathing_request("can't breathe") == True

def test_detect_booking_request():
    assert IntelligenceService.detect_booking_request("I want to book appointment") == True
    assert IntelligenceService.detect_booking_request("schedule therapy") == True
    assert IntelligenceService.detect_booking_request("I like therapy") == False

def test_extract_email():
    assert IntelligenceService.extract_email("my email is test@example.com") == "test@example.com"
    assert IntelligenceService.extract_email("contact me at user.name123@domain.co.in please") == "user.name123@domain.co.in"
    assert IntelligenceService.extract_email("no email here") is None
