"""Settings loaded from the environment, with local defaults that match infra/docker-compose.yml."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # protected_namespaces=() so the MODEL_* fields don't collide with pydantic's model_ prefix
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    database_url: str = "postgresql+psycopg://dev:dev@localhost:5432/greenroom"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "dev"
    s3_secret_key: str = "devdevdev"
    s3_bucket: str = "greenroom"

    livekit_url: str = "ws://localhost:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "secret"

    openai_api_key: str = ""

    model_conversation: str = ""
    model_router: str = ""
    model_scorer: str = ""
    model_report: str = ""

    cassette_mode: str = "off"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
