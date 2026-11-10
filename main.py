from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent

from app.config import get_settings
from app.database import init_db
from app.handlers import (
    common,
    drivers,
    reports,
    settings as settings_rt,
    tickets,
    trips,
    trucks,
)
from app.middlewares import AdminMiddleware
from app.services.scheduler import (
    ReportScheduler,
    set_report_scheduler,
)

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Inicio"),
    BotCommand(command="menu", description="Menú principal"),
    BotCommand(command="viajes", description="Lista de viajes"),
    BotCommand(command="nuevoviaje", description="Registrar un viaje"),
    BotCommand(command="camiones", description="Administrar camiones"),
    BotCommand(command="conductores", description="Administrar conductores"),
    BotCommand(command="tickets", description="Administrar tickets"),
    BotCommand(command="semana", description="Resumen de la semana actual"),
    BotCommand(command="reporte", description="Excel semanal"),
    BotCommand(command="configuracion", description="Reporte automático"),
    BotCommand(command="ayuda", description="Ayuda"),
    BotCommand(command="cancelar", description="Cancelar el paso actual"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    init_db()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(AdminMiddleware())
    dispatcher.callback_query.outer_middleware(AdminMiddleware())
    dispatcher.include_routers(
        common.router,
        trucks.router,
        drivers.router,
        trips.router,
        tickets.router,
        reports.router,
        settings_rt.router,
    )

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.error("Error no controlado", exc_info=event.exception)
        return True

    scheduler = ReportScheduler(bot)
    set_report_scheduler(scheduler)

    await bot.set_my_commands(COMMANDS)
    scheduler.start()
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await scheduler.stop()
        set_report_scheduler(None)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
