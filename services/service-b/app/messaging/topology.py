import logging

from aio_pika import ExchangeType
from aio_pika.abc import (
    AbstractRobustChannel,
    AbstractRobustExchange,
    AbstractRobustQueue,
)

from app.config import settings

logger = logging.getLogger("service-b.topology")


async def setup_topology(
    channel: AbstractRobustChannel,
) -> tuple[AbstractRobustExchange, AbstractRobustQueue, AbstractRobustExchange, AbstractRobustQueue]:
    """Idempotently declares exchanges, queues, DLX, DLQ, and bindings.
    
    Returns:
        tuple containing (main_exchange, work_queue, dlx_exchange, dlq_queue)
    """
    logger.info("Declaring AMQP topology...")

    # 1. Declare the Dead Letter Exchange (DLX)
    dlx_exchange = await channel.declare_exchange(
        name=settings.rabbitmq_dlx_name,
        type=ExchangeType.DIRECT,
        durable=True,
    )

    # 2. Declare the Dead Letter Queue (DLQ) and bind to DLX
    dlq = await channel.declare_queue(
        name=settings.rabbitmq_dlq_name,
        durable=True,
    )
    # Any message dead-lettered with routing key "task.work" lands in this DLQ
    await dlq.bind(exchange=dlx_exchange, routing_key="task.work")
    logger.info("Bound DLQ '%s' to DLX '%s'", settings.rabbitmq_dlq_name, settings.rabbitmq_dlx_name)

    # 3. Declare the Primary Exchange
    main_exchange = await channel.declare_exchange(
        name="sandbox.exchange",
        type=ExchangeType.DIRECT,
        durable=True,
    )

    # 4. Declare the Primary Work Queue with Dead Letter routing
    # The 'x-dead-letter-exchange' argument tells RabbitMQ where to route rejected messages
    work_queue = await channel.declare_queue(
        name=settings.rabbitmq_queue_name,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.rabbitmq_dlx_name,
        },
    )

    # Bind the work queue to the primary exchange
    await work_queue.bind(exchange=main_exchange, routing_key="task.work")
    logger.info(
        "Bound work queue '%s' to exchange '%s' with routing_key 'task.work' (DLX: %s)",
        settings.rabbitmq_queue_name,
        "sandbox.exchange",
        settings.rabbitmq_dlx_name,
    )

    return main_exchange, work_queue, dlx_exchange, dlq
