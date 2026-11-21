from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
    )
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"


def create_chat_model(settings: Settings) -> ChatOpenAI | None:
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        return None
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout=30,
        max_retries=0,
        use_responses_api=False,
    )
