from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, Engine, make_url
from sqlmodel import Session, create_engine


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: PostgresDsn | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "ecomm_assistant"
    postgres_user: str = "ecomm"
    postgres_password: SecretStr = SecretStr("ecomm")

    def connection_url(self) -> URL:
        if self.database_url is not None:
            url = make_url(str(self.database_url))
            return url.set(drivername="postgresql+psycopg")

        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


def create_database_engine(*, pool_pre_ping: bool = True) -> Engine:
    return create_engine(
        DatabaseSettings().connection_url(),
        pool_pre_ping=pool_pre_ping,
        connect_args={"connect_timeout": 3},
    )


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.database_engine) as session:
        yield session
