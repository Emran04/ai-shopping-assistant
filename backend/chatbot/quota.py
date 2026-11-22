from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID, uuid4

from models import ChatCustomer
from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, update
from sqlmodel import Session, select


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_prefix="CHAT_",
        env_ignore_empty=True,
        extra="ignore",
    )

    message_limit: PositiveInt = 20


@dataclass(frozen=True)
class CustomerUsage:
    customer_id: UUID
    messages_used: int
    new_token: str | None = None


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def get_customer_usage(engine: Engine, token: str | None) -> CustomerUsage:
    with Session(engine) as session, session.begin():
        if token:
            customer = session.exec(
                select(ChatCustomer).where(ChatCustomer.token_digest == token_digest(token))
            ).one_or_none()
            if customer is not None:
                return CustomerUsage(customer.id, customer.messages_used)

        token = token_urlsafe(32)
        customer = ChatCustomer(id=uuid4(), token_digest=token_digest(token))
        session.add(customer)
        return CustomerUsage(customer.id, customer.messages_used, token)


def reserve_message(engine: Engine, customer_id: UUID, limit: int) -> int | None:
    with Session(engine) as session, session.begin():
        return session.execute(
            update(ChatCustomer)
            .where(ChatCustomer.id == customer_id, ChatCustomer.messages_used < limit)
            .values(messages_used=ChatCustomer.messages_used + 1)
            .returning(ChatCustomer.messages_used)
        ).scalar_one_or_none()


def reset_usage(engine: Engine, customer_id: UUID) -> bool:
    with Session(engine) as session, session.begin():
        return session.execute(
            update(ChatCustomer)
            .where(ChatCustomer.id == customer_id)
            .values(messages_used=0)
            .returning(ChatCustomer.id)
        ).scalar_one_or_none() is not None
