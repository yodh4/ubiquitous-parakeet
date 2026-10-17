from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-a"
    port: int = 8000
    service_b_url: str = "http://service-b:8001"
    request_timeout_seconds: float = 5.0

    model_config = SettingsConfigDict(
        env_prefix="SERVICE_A_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
