from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    model_file: str = ""
    hf_token: str = ""
    device: Literal["auto", "cpu", "cuda"] = "auto"

    max_context: int = 4096
    max_new_tokens: int = 1024
    temperature: float = 0.7

    cors_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
