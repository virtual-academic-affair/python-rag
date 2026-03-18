"""
Gemini Client - Core client initialization (Singleton).
"""

from typing import Optional
from google import genai
from app.core.config import settings

class GeminiClient:
    """
    Singleton service for Gemini API client initialization.
    """
    
    _instance: Optional["GeminiClient"] = None
    _client: Optional[genai.Client] = None
    
    def __new__(cls):
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize Gemini client (only once)."""
        if self._client is None:
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    
    @property
    def client(self) -> genai.Client:
        """Get the Gemini client instance."""
        if self._client is None:
            raise RuntimeError("Gemini client not initialized")
        return self._client

gemini_client = GeminiClient()
