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

    # Phase 2 measures these combinations against the 800 ms gate and picks.
    stt_provider: str = "openai"  # openai | deepgram
    tts_provider: str = "openai"  # openai | cartesia
    deepgram_api_key: str = ""
    cartesia_api_key: str = ""

    # Pinned explicitly, not left to the plugin's default, so a plugin upgrade
    # cannot silently move us onto a pricier model.
    #   STT  gpt-4o-mini-transcribe  $0.003/min  <- half of whisper-1
    #        gpt-4o-transcribe       $0.006/min
    #        realtime transcription  $0.017/min  <- 5.7x; only if phase 2 needs
    #                                              interim results to hit 800 ms
    #   TTS  gpt-4o-mini-tts         ~$0.015/min audio, steerable
    #        tts-1                   $15/1M chars  (about the same for our turns)
    #        tts-1-hd                $30/1M chars  <- 2x for quality a mock
    #                                                 interview does not need
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "ash"

    model_conversation: str = ""
    model_router: str = ""
    model_scorer: str = ""
    model_report: str = ""

    cassette_mode: str = "off"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
