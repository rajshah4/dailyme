from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost/dailyme"

    # Gmail
    gmail_credentials_json: str = "credentials.json"
    gmail_token_json: str = "token.json"
    gmail_inbox_address: str = ""

    # SendGrid
    sendgrid_api_key: str = ""
    digest_to_email: str = ""
    digest_from_email: str = "digest@dailyme.app"

    # LLM (for newsletter story extraction)
    llm_model: str = "anthropic/claude-sonnet-4-5-20250929"
    llm_api_key: str = ""
    llm_base_url: str = ""

    # Schedule
    digest_hour: int = 8
    digest_timezone: str = "US/Eastern"
    poll_interval_seconds: int = 120

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
