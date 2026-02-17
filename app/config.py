from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "events_app"
    google_maps_api_key: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # LM Studio (OpenAI-compatible API)
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen3-14b"

    model_config = {"env_file": ".env"}


settings = Settings()
