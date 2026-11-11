from aiogram.fsm.state import State, StatesGroup


class TripCreate(StatesGroup):
    truck = State()
    driver = State()
    input = State()
    date = State()
    status = State()
    notes = State()
    confirm = State()


class TripEdit(StatesGroup):
    menu = State()
    input = State()


class TruckForm(StatesGroup):
    name = State()


class DriverForm(StatesGroup):
    name = State()
    phone = State()


class TicketFlow(StatesGroup):
    media = State()
    amount = State()


class ReportFlow(StatesGroup):
    date = State()


class SettingsFlow(StatesGroup):
    time = State()
