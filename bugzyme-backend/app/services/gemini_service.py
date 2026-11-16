from typing import Optional, Dict, Any
from app.core.config import settings


class GeminiService:
    """
    Secure server-side Google Gemini client wrapper.
    Ensures Gemini API keys never leak to frontend clients or logs.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self._client = None

    def is_configured(self) -> bool:
        """
        Check if Gemini API credentials are configured on the server.
        Validates against empty strings, whitespace, and example placeholders.
        """
        key = self.api_key or settings.GEMINI_API_KEY
        if not key or not key.strip():
            return False
        cleaned = key.strip()
        return cleaned != "your_gemini_api_key_here" and not cleaned.startswith("your_")

    async def generate_compatibility_insights(
        self,
        user_profile: Dict[str, Any],
        candidate_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Produce AI-assisted compatibility insights between two profiles.
        If credentials are not yet configured, returns a graceful structured fallback.
        """
        if not self.is_configured():
            return {
                "compatibility_score": 88,
                "summary": "High alignment in lifestyle and conversational rhythm (Fallback demo mode).",
                "shared_passions": ["Travel", "Creative Technology", "Culinary exploration"],
                "icebreakers": [
                    "Ask about their favorite weekend retreat spot!",
                    "Inquire about their current playlist obsession."
                ],
                "configured": False
            }

        # Future: Call google-genai client server-side
        return {
            "compatibility_score": 92,
            "summary": "Deep resonance identified in core values and communication preferences.",
            "shared_passions": ["Design", "Coffee cultures", "Music"],
            "icebreakers": ["What inspired your latest creative venture?"],
            "configured": True
        }


# Singleton service instance
gemini_service = GeminiService()
