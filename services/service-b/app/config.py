from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-b"
    port: int = 8001

    model_config = SettingsConfigDict(
        env_prefix="SERVICE_B_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
