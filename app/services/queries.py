from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BotSettings,
    Driver,
    Ticket,
    TicketKind,
    TicketMedia,
    Trip,
    TripStatus,
    Truck,
)

PAGE_SIZE = 5


def _page(items: list, page: int) -> tuple[list, bool]:
    return items[:PAGE_SIZE], len(items) > PAGE_SIZE


def _paginate(stmt, db: Session, page: int):
    result = db.scalars(stmt.limit(PAGE_SIZE + 1).offset(page * PAGE_SIZE)).all()
    return list(result[:PAGE_SIZE]), len(result) > PAGE_SIZE


def list_trucks(db: Session, page: int = 0, active_only: bool = False):
    stmt = select(Truck)
    if active_only:
        stmt = stmt.where(Truck.active.is_(True))
    stmt = stmt.order_by(Truck.active.desc(), Truck.name.asc())
    return _paginate(stmt, db, page)


def all_active_trucks(db: Session) -> list[Truck]:
    return list(
        db.scalars(
            select(Truck).where(Truck.active.is_(True)).order_by(Truck.name.asc())
        ).all()
    )


def all_trucks(db: Session) -> list[Truck]:
    return list(
        db.scalars(select(Truck).order_by(Truck.active.desc(), Truck.name.asc())).all()
    )


def get_truck(db: Session, truck_id: int) -> Truck | None:
    return db.get(Truck, truck_id)


def truck_name_exists(db: Session, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Truck.id).where(func.lower(Truck.name) == name.strip().lower())
    if exclude_id is not None:
        stmt = stmt.where(Truck.id != exclude_id)
    return db.scalar(stmt) is not None


def create_truck(db: Session, name: str) -> Truck:
    truck = Truck(name=name.strip())
    db.add(truck)
    db.flush()
    return truck


def update_truck(db: Session, truck: Truck, **fields) -> Truck:
    for key, value in fields.items():
        setattr(truck, key, value)
    db.flush()
    return truck


def delete_truck(db: Session, truck: Truck) -> None:
    db.delete(truck)
    db.flush()


def count_trips_for_truck(db: Session, truck_id: int) -> int:
    return int(
        db.scalar(select(func.count(Trip.id)).where(Trip.truck_id == truck_id)) or 0
    )


def list_drivers(db: Session, page: int = 0, active_only: bool = False):
    stmt = select(Driver)
    if active_only:
        stmt = stmt.where(Driver.active.is_(True))
    stmt = stmt.order_by(Driver.active.desc(), Driver.name.asc())
    return _paginate(stmt, db, page)


def all_active_drivers(db: Session) -> list[Driver]:
    return list(
        db.scalars(
            select(Driver).where(Driver.active.is_(True)).order_by(Driver.name.asc())
        ).all()
    )


def all_drivers(db: Session) -> list[Driver]:
    return list(
        db.scalars(
            select(Driver).order_by(Driver.active.desc(), Driver.name.asc())
        ).all()
    )


def get_driver(db: Session, driver_id: int) -> Driver | None:
    return db.get(Driver, driver_id)


def create_driver(db: Session, name: str, phone: str | None = None) -> Driver:
    driver = Driver(name=name.strip(), phone=phone)
    db.add(driver)
    db.flush()
    return driver


def update_driver(db: Session, driver: Driver, **fields) -> Driver:
    for key, value in fields.items():
        setattr(driver, key, value)
    db.flush()
    return driver


def delete_driver(db: Session, driver: Driver) -> None:
    db.delete(driver)
    db.flush()


def count_trips_for_driver(db: Session, driver_id: int) -> int:
    return int(
        db.scalar(select(func.count(Trip.id)).where(Trip.driver_id == driver_id)) or 0
    )


def _trip_options():
    return (
        selectinload(Trip.truck),
        selectinload(Trip.driver),
        selectinload(Trip.tickets),
    )


def get_trip(db: Session, trip_id: int) -> Trip | None:
    return db.scalar(
        select(Trip).where(Trip.id == trip_id).options(*_trip_options())
    )


def list_trips(db: Session, page: int = 0):
    stmt = (
        select(Trip)
        .options(*_trip_options())
        .order_by(Trip.trip_date.desc(), Trip.id.desc())
    )
    return _paginate(stmt, db, page)


def trips_for_report(
    db: Session,
    start: date,
    end: date,
    truck_id: int | None = None,
) -> list[Trip]:
    stmt = (
        select(Trip)
        .join(Trip.truck)
        .where(Trip.trip_date >= start, Trip.trip_date <= end)
        .options(*_trip_options())
        .order_by(Truck.name.asc(), Trip.trip_date.asc(), Trip.id.asc())
    )
    if truck_id is not None:
        stmt = stmt.where(Trip.truck_id == truck_id)
    return list(db.scalars(stmt).all())


def create_trip(
    db: Session,
    *,
    truck_id: int,
    driver_id: int,
    status: TripStatus,
    trip_date: date,
    origin: str,
    destination: str,
    distance_miles: Decimal,
    duration_minutes: int,
    cargo_weight: Decimal,
    driver_percentage: Decimal,
    cargo_payment: Decimal,
    notes: str | None,
    created_by: int,
) -> Trip:
    trip = Trip(
        truck_id=truck_id,
        driver_id=driver_id,
        status=status,
        trip_date=trip_date,
        origin=origin.strip(),
        destination=destination.strip(),
        distance_miles=distance_miles,
        duration_minutes=duration_minutes,
        cargo_weight=cargo_weight,
        driver_percentage=driver_percentage,
        cargo_payment=cargo_payment,
        notes=notes.strip() if notes else None,
        created_by=created_by,
    )
    db.add(trip)
    db.flush()
    return trip


def update_trip(db: Session, trip: Trip, **fields) -> Trip:
    for key, value in fields.items():
        setattr(trip, key, value)
    db.flush()
    return trip


def delete_trip(db: Session, trip: Trip) -> None:
    db.delete(trip)
    db.flush()


def add_ticket(
    db: Session,
    *,
    trip_id: int,
    kind: TicketKind,
    media_type: TicketMedia,
    file_id: str,
    file_unique_id: str,
    caption: str | None,
    width: int | None,
    height: int | None,
    uploaded_by: int,
) -> tuple[Ticket, bool]:
    existing = db.scalar(
        select(Ticket).where(
            Ticket.trip_id == trip_id,
            Ticket.telegram_file_unique_id == file_unique_id,
        )
    )
    if existing is not None:
        return existing, False

    ticket = Ticket(
        trip_id=trip_id,
        kind=kind,
        media_type=media_type,
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        caption=caption,
        width=width,
        height=height,
        uploaded_by=uploaded_by,
    )
    db.add(ticket)
    db.flush()
    return ticket, True


def list_tickets(db: Session, trip_id: int) -> list[Ticket]:
    return list(
        db.scalars(
            select(Ticket)
            .where(Ticket.trip_id == trip_id)
            .order_by(Ticket.created_at.asc(), Ticket.id.asc())
        ).all()
    )


def get_bot_settings(db: Session) -> BotSettings:
    config = db.get(BotSettings, 1)
    if config is None:
        config = BotSettings(id=1)
        db.add(config)
        db.flush()
    return config


def update_bot_settings(db: Session, **fields) -> BotSettings:
    config = get_bot_settings(db)
    for key, value in fields.items():
        setattr(config, key, value)
    db.flush()
    return config
