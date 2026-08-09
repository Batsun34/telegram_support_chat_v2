import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.handlers import common, moderator, user
from app.middlewares import DbSessionMiddleware, ModeratorSerialMiddleware
from app.services.chats import ChatService
from app.services.housekeeping import HousekeepingService
from app.services.notifier import NotificationDebouncer
from app.services.views import ViewService


async def main() -> None:
    settings = get_settings()
    if not settings.moderators:
        raise RuntimeError("MODERATORS_JSON пуст: добавьте хотя бы одного модератора")

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    chat_service = ChatService(settings)
    view_service = ViewService(bot, settings, session_factory, chat_service)
    notifier = NotificationDebouncer(
        bot,
        settings,
        session_factory,
        chat_service,
        view_service,
    )
    housekeeping = HousekeepingService(view_service)

    dp = Dispatcher()
    dp["settings"] = settings
    dp["chat_service"] = chat_service
    dp["view_service"] = view_service
    dp["notifier"] = notifier

    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    moderator_serial = ModeratorSerialMiddleware(settings)
    dp.message.middleware(moderator_serial)
    dp.callback_query.middleware(moderator_serial)

    # /start first, then moderator controls, then ordinary user messages.
    dp.include_router(common.router)
    dp.include_router(moderator.router)
    dp.include_router(user.router)

    try:
        await notifier.recover_pending()
        await housekeeping.start()
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await notifier.shutdown()
        await housekeeping.stop()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
