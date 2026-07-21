from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Library
    library_roots: str = "/library"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Storage
    database_url: str = "sqlite:////data/subs.db"
    data_dir: str = "/data"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Whisper
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_vad: bool = True

    # Translator
    deepseek_api_key: str = ""
    openai_base_url: str = "https://api.deepseek.com/v1"
    translate_model: str = "deepseek-chat"

    @property
    def library_root_paths(self) -> list[str]:
        return [p for p in self.library_roots.split(":") if p]


settings = Settings()
