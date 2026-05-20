from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker


def configure_broker(redis_url: str) -> RedisBroker:
    broker = RedisBroker(url=redis_url)  # type: ignore[no-untyped-call]
    dramatiq.set_broker(broker)
    return broker
