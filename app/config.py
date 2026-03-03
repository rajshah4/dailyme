from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost/dailyme"

    # Gmail
    gmail_credentials_json: str = "credentials.json"
    gmail_token_json: str = "token.json"
    gmail_inbox_address: str = ""

    # Schedule
    poll_interval_seconds: int = 120

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
