from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TripStatus(str, enum.Enum):
    in_progress = "in_progress"
    finished = "finished"


class TicketKind(str, enum.Enum):
    fuel = "fuel"
    maintenance = "maintenance"
    other = "other"


class TicketMedia(str, enum.Enum):
    photo = "photo"
    document = "document"


def enum_column(enum_type: type[enum.Enum], length: int = 24):
    return Enum(
        enum_type,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [item.value for item in cls],
    )


class Truck(Base):
    __tablename__ = "trucks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    trips: Mapped[list[Trip]] = relationship(back_populates="truck")


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    trips: Mapped[list[Trip]] = relationship(back_populates="driver")


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    truck_id: Mapped[int] = mapped_column(
        ForeignKey("trucks.id", ondelete="RESTRICT"), index=True
    )
    driver_id: Mapped[int] = mapped_column(
        ForeignKey("drivers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[TripStatus] = mapped_column(
        enum_column(TripStatus), default=TripStatus.in_progress, index=True
    )
    trip_date: Mapped[date] = mapped_column(Date, index=True)
    origin: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(160))
    distance_miles: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    cargo_weight: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    driver_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cargo_payment: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow_naive, onupdate=utcnow_naive
    )

    truck: Mapped[Truck] = relationship(back_populates="trips")
    driver: Mapped[Driver] = relationship(back_populates="trips")
    tickets: Mapped[list[Ticket]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def driver_pay(self) -> Decimal:
        return (self.cargo_payment * self.driver_percentage / Decimal(100)).quantize(
            Decimal("0.01")
        )


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint(
            "trip_id",
            "telegram_file_unique_id",
            name="uq_ticket_trip_file",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[TicketKind] = mapped_column(enum_column(TicketKind), index=True)
    media_type: Mapped[TicketMedia] = mapped_column(enum_column(TicketMedia))
    telegram_file_id: Mapped[str] = mapped_column(String(255))
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255))
    caption: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    trip: Mapped[Trip] = relationship(back_populates="tickets")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    report_day: Mapped[int] = mapped_column(Integer, default=6)
    report_time: Mapped[str] = mapped_column(String(5), default="09:00")
    report_enabled: Mapped[bool] = mapped_column(default=True)
    report_scope: Mapped[str] = mapped_column(String(20), default="general")
    report_truck_id: Mapped[int | None] = mapped_column(
        ForeignKey("trucks.id", ondelete="SET NULL"), nullable=True
    )
    report_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_sent_week_start: Mapped[date | None] = mapped_column(Date, nullable=True)
