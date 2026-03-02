import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
from db import init_db
from handlers import admin_router, user_router
from middleware import ThrottleMiddleware


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def main():
    setup_logging()
    logger = logging.getLogger(__name__)

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()

    dp.message.middleware(ThrottleMiddleware())

    dp.include_router(user_router)
    dp.include_router(admin_router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
