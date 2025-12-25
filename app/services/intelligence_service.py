import re
from typing import Dict, List, Optional, Tuple

class IntelligenceService:
    # Crisis detection keywords - COMPREHENSIVE LIST
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

    FAREWELL_PHRASES = [
        "bye", "goodbye", "good bye", "see you", "take care",
        "that's all", "thats all", "i'm done", "im done", "thank you bye",
        "thanks bye", "end call", "hang up", "gotta go", "need to go",
        "talk later", "bye bye", "tata", "alvida", "dhanyavaad", "shukriya"
    ]
    
    # Confirmation phrases (for accepting appointment suggestions)
    CONFIRMATION_PHRASES = [
        "yes", "ok", "okay", "sure", "yeah", "yep", "yup", "yes please",
        "go ahead", "sounds good", "please", "i'd like that", "i would like that",
        "let's do it", "lets do it", "that would be great", "that would be nice",
        "i'm interested", "im interested", "book it", "definitely", "absolutely",
        "of course", "why not", "alright", "fine", "i agree", "i want that",
        "send it", "send me", "yes send", "please send"
    ]
    
    # Decline phrases (for declining appointment suggestions)
    DECLINE_PHRASES = [
        "no", "not now", "maybe later", "no thanks", "no thank you", "nope",
        "not interested", "skip", "not yet", "i'm good", "im good", "i'm fine",
        "im fine", "no need", "don't want", "dont want", "not right now",
        "another time", "some other time", "pass", "not today", "i'll think about it",
        "ill think about it", "let me think", "i'm not sure", "im not sure"
    ]

    @classmethod
    def detect_crisis(cls, text: str) -> bool:
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in cls.CRISIS_KEYWORDS)

    @classmethod
    def detect_mood(cls, text: str) -> str:
        text_lower = text.lower()
        for mood, keywords in cls.MOOD_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return mood
        return "neutral"

    @classmethod
    def detect_breathing_request(cls, text: str) -> bool:
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in cls.BREATHING_TRIGGERS)

    @classmethod
    def detect_booking_request(cls, text: str) -> bool:
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in cls.BOOKING_TRIGGERS)

    @classmethod
    def detect_farewell(cls, text: str) -> bool:
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in cls.FAREWELL_PHRASES)

    @classmethod
    def extract_email(cls, text: str) -> Optional[str]:
        if "@" in text and "." in text:
            # Try to extract email from text
            email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
            email_match = re.search(email_pattern, text)
            if email_match:
                return email_match.group()
        return None
    
    @classmethod
    def detect_confirmation(cls, text: str) -> bool:
        """Detect if user is confirming/agreeing (e.g., to an appointment suggestion)"""
        text_lower = text.lower().strip()
        # Check for exact matches for short phrases
        if text_lower in ["yes", "ok", "okay", "sure", "yeah", "yep", "yup", "please", "alright", "fine"]:
            return True
        # Check for phrase matches
        return any(phrase in text_lower for phrase in cls.CONFIRMATION_PHRASES)
    
    @classmethod
    def detect_decline(cls, text: str) -> bool:
        """Detect if user is declining (e.g., an appointment suggestion)"""
        text_lower = text.lower().strip()
        # Check for exact matches for short phrases
        if text_lower in ["no", "nope", "nah", "pass", "skip"]:
            return True
        # Check for phrase matches
        return any(phrase in text_lower for phrase in cls.DECLINE_PHRASES)

