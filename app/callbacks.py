from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="menu"):
    action: str


class TruckCB(CallbackData, prefix="truck"):
    action: str
    truck_id: int = 0
    page: int = 0


class DriverCB(CallbackData, prefix="driver"):
    action: str
    driver_id: int = 0
    page: int = 0


class TripCB(CallbackData, prefix="trip"):
    action: str
    trip_id: int = 0
    page: int = 0
    value: str = ""


class TicketCB(CallbackData, prefix="ticket"):
    action: str
    trip_id: int = 0
    page: int = 0
    value: str = ""


class ReportCB(CallbackData, prefix="report"):
    action: str
    scope: str = ""
    week: str = ""
    truck_id: int = 0
    page: int = 0


class SettingsCB(CallbackData, prefix="settings"):
    action: str
    value: str = ""
    page: int = 0
