from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    temp_dir: Path = Path('tmp')
    cors_origins: list[str] = ['http://localhost:3000']
    max_concurrent: int = Field(2, ge=1, le=8)
    max_tasks: int = Field(30, ge=1)
    max_duration: int = Field(7200, ge=1)
    max_bytes: int = Field(2_000_000_000, ge=1)
    task_timeout: int = Field(1800, ge=1)
    retention_seconds: int = Field(3600, ge=1)
    ffmpeg_path: str = 'ffmpeg'
    ffprobe_path: str = 'ffprobe'


settings = Settings()
