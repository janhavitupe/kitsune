from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    # Meta Model API (OpenAI-compatible)
    model_api_key: str = ""
    model_api_base_url: str = "https://api.meta.ai/v1"
    spark_model: str = "muse-spark-1.3"
    wonder_model: str = "muse-wonder-1.0"
    image_model: str = "muse-image-1.0"
    voice_model: str = "muse-voice-transcribe-1.0"
    sam_model: str = "sam-3.1"

    # Open-weights endpoint (Baseten primary, Fireworks fallback)
    openweights_base_url: str = ""
    openweights_api_key: str = ""
    openweights_model: str = ""

    data_dir: Path = REPO_ROOT / "data"
    cors_origins: str = "http://localhost:5173"
    ai_offline: bool = False  # serve only from ai_cache, never call models
    demo_password: str = ""

    # Upload limits
    max_upload_mb: int = 25
    max_side_px: int = 8000
    thumb_px: int = 320

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
