from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    base_url: str = "https://tributary-stroller-antsy.ngrok-free.dev"

    media_dir: Path = Path("media")
    db_path: Path = Path("data/app.db")
    verification_dir: Path = Path("verification")

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/callback"


settings = Settings()
