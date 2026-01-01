"""
Configuration management using pydantic-settings.
Reads from .env file and environment variables.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration"""
    
    # AI / LLM Configuration
    groq_api_key: str = "test-key-configure-in-env"
    # Dual-model setup: fast primary + capable fallback
    # Primary: fast model for quick parsing (highest rate limits)
    # Fallback: more capable model for complex/ambiguous cases
    llm_model: str = "llama-3.1-8b-instant"  # Primary: fast, high limits
    llm_model_fallback: str = "llama-3.3-70b-versatile"  # Fallback: more capable

    # Rephrase / phraser pipeline (used when deterministic parsing is ambiguous)
    enable_llm_rephrase: bool = True

    # Baseten OpenAI-compatible endpoint (optional)
    baseten_api_key: str | None = None
    baseten_base_url: str = "https://inference.baseten.co/v1"
    baseten_model: str = "openai/gpt-oss-120b"
    baseten_timeout_seconds: float = 12.0

    # Optional 3rd rephrase model (Groq). If unset, uses llm_model_fallback.
    llm_model_rephrase_third: str | None = None
    
    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # File Upload Limits
    max_file_size_mb: int = 100
    max_files_per_request: int = 5
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
