from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime

from aiogram import Bot

from app.config import get_settings
from app.database import session_scope
from app.services.queries import get_bot_settings, get_truck, trips_for_report
from app.services.reports import send_report
from app.services.weeks import current_week_bounds, next_report_run

logger = logging.getLogger(__name__)

_scheduler: "ReportScheduler | None" = None


def set_report_scheduler(scheduler: "ReportScheduler | None") -> None:
    global _scheduler
    _scheduler = scheduler


def notify_report_scheduler() -> None:
    if _scheduler is not None:
        _scheduler.notify_change()


class ReportScheduler:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="report-scheduler")

    def notify_change(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _wait(self, timeout: float | None) -> bool:
        try:
            if timeout is None:
                await self._wake.wait()
            else:
                await asyncio.wait_for(self._wake.wait(), timeout=max(timeout, 0))
            self._wake.clear()
            return True
        except asyncio.TimeoutError:
            return False

    async def _run(self) -> None:
        while not self._stopping:
            with session_scope() as db:
                config = get_bot_settings(db)
                enabled = config.report_enabled
                weekday = config.report_day
                time_text = config.report_time

            if not enabled:
                await self._wait(None)
                continue

            now = datetime.now(get_settings().tz)
            next_run = next_report_run(now, weekday, time_text)
            changed = await self._wait((next_run - now).total_seconds())
            if self._stopping:
                break
            if changed:
                continue

            try:
                await self._send_scheduled()
            except Exception:
                logger.exception("Error al enviar el reporte automático")
            await self._wait(60)

    async def _send_scheduled(self) -> None:
        settings = get_settings()
        week_start, week_end = current_week_bounds()

        with session_scope() as db:
            config = get_bot_settings(db)
            if not config.report_enabled:
                return
            truck = (
                get_truck(db, config.report_truck_id)
                if config.report_scope == "truck" and config.report_truck_id
                else None
            )
            general = truck is None
            trips = trips_for_report(
                db,
                week_start,
                week_end,
                None if general else truck.id,
            )
            scope_label = (
                "Reporte general"
                if general
                else f"Reporte del camión {truck.name}"
            )
            configured_chat = config.report_chat_id
            truck_id = None if general else truck.id

        targets: list[int] = []
        if configured_chat:
            targets.append(configured_chat)
        else:
            targets.extend(sorted(settings.admin_id_set))

        sent = False
        for chat_id in targets:
            try:
                await send_report(
                    self.bot,
                    chat_id,
                    trips,
                    week_start,
                    week_end,
                    general=general,
                    scope_label=scope_label,
                    truck_id=truck_id,
                )
                sent = True
                break
            except Exception:
                logger.exception(
                    "No se pudo enviar el reporte automático al chat %s", chat_id
                )

        if sent:
            with session_scope() as db:
                config = get_bot_settings(db)
                config.last_sent_week_start = week_start
            logger.info(
                "Reporte automático enviado para la semana %s", week_start.isoformat()
            )
