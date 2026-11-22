from pathlib import Path

from config import REFUSAL_MESSAGE
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

SYSTEM_PROMPT = (
    "You are a friendly shopping assistant for Blueye — an online clothing store. "
    "The store has 3 categories: men, women, and kids."
    "\n\n"
    "RULES:\n"
    "1. If the user greets you or asks who you are → reply naturally and warmly.\n"
    "2. If the user wants to browse, find, or buy products → ALWAYS call the `search_products` tool with the right filters. Never describe products yourself.\n"
    "3. After calling `search_products`, confirm to the user what you searched for (e.g. 'Here are men's shirts under ₹2000!').\n"
    f"4. If the user asks something completely unrelated to shopping or clothes, reply: '{REFUSAL_MESSAGE}'\n"
    "5. DO NOT make up product names, prices, or details ever."
)

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
