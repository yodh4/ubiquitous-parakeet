from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "service-b"
    port: int = 8001

    # RabbitMQ Broker Configuration (Milestone 3)
    rabbitmq_url: str = "amqp://guest:guest@localhost:5673/"
    rabbitmq_queue_name: str = "sandbox.tasks.work"
    rabbitmq_dlx_name: str = "sandbox.dlx"
    rabbitmq_dlq_name: str = "sandbox.tasks.dlq"
    rabbitmq_prefetch_count: int = 5
    idempotency_ttl_seconds: int = 300
    idempotency_max_capacity: int = 10000

    model_config = SettingsConfigDict(
        env_prefix="SERVICE_B_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
