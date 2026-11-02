from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-a"
    port: int = 8000
    service_b_url: str = "http://service-b:8001"
    request_timeout_seconds: float = 1.0  # FR-2.1: Strict default timeout (1s)

    # Resilience defaults
    default_max_retries: int = 3
    default_base_delay_ms: float = 50.0
    default_max_delay_ms: float = 1000.0
    cb_failure_threshold: int = 3
    cb_recovery_timeout_seconds: float = 5.0

    # RabbitMQ Broker Configuration (Milestone 3)
    rabbitmq_url: str = "amqp://guest:guest@localhost:5673/"
    rabbitmq_exchange_name: str = "sandbox.exchange"
    rabbitmq_routing_key: str = "task.work"

    model_config = SettingsConfigDict(
        env_prefix="SERVICE_A_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
