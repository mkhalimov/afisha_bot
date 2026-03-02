import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)

# Per-user throttle state: user_id -> (last_message_time, warned)
_user_timestamps: dict[int, tuple[float, bool]] = {}

RATE_LIMIT_SECONDS = 1.0
SILENCE_SECONDS = 3.0


class ThrottleMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user
        if not user:
            return await handler(event, data)

        user_id = user.id
        now = time.monotonic()
        last_time, warned = _user_timestamps.get(user_id, (0.0, False))
        delta = now - last_time

        if delta < RATE_LIMIT_SECONDS:
            if not warned:
                _user_timestamps[user_id] = (last_time, True)
                await event.answer("Не так быстро! Подожди секунду.")
            elif delta < SILENCE_SECONDS:
                # silently drop
                pass
            else:
                # still within silence window but warned flag already set — reset
                _user_timestamps[user_id] = (now, False)
                return await handler(event, data)
            return None

        _user_timestamps[user_id] = (now, False)
        return await handler(event, data)
