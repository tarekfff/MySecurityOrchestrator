from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    supabase_url: str
    supabase_service_key: str

    pdf_path: str = (
        "The Web Application Hacker's Handbook - Finding and Exploiting Security Flaws, "
        "2nd Edition by Dafydd Stuttard, Marcus Pinto.pdf"
    )

    embed_batch_size: int = 20
    embed_delay_seconds: float = 1.0
    chunk_max_words: int = 250
    chunk_min_words: int = 50

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def pdf_path_resolved(self) -> Path:
        return Path(self.pdf_path)


settings = Settings()
