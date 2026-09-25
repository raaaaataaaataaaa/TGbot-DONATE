"""Модели SQLAlchemy и асинхронная сессия БД."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PaymentProvider(str, enum.Enum):
    ROLLYPAY = "rollypay"
    CRYPTOBOT = "cryptobot"
    PLATEGA = "platega"
    TG_STARS = "tg_stars"


class PaymentStatus(str, enum.Enum):
    NEW = "new"            # создано, ожидает оплаты
    PAID = "paid"          # оплачено
    FAILED = "failed"      # отменено / ошибка
    EXPIRED = "expired"    # истёкло время оплаты
    REFUNDED = "refunded"  # возврат


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    is_admin: Mapped[bool] = mapped_column(default=False)
    total_donated: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payments: Mapped[list["Payment"]] = relationship(back_populates="user")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[PaymentProvider] = mapped_column(Enum(PaymentProvider))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="RUB")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.NEW, index=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")


class Setting(Base):
    """Хранилище настроек бота, редактируемых из админ-панели."""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


engine = create_async_engine(config.DATABASE_URL, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Синхронизируем флаг админов из конфига
    async with session_factory() as s:
        for admin_id in config.ADMIN_IDS:
            exists = await s.scalar(select(User).where(User.tg_id == admin_id))
            if not exists:
                s.add(User(tg_id=admin_id, full_name="admin", is_admin=True))
            else:
                exists.is_admin = True
        await s.commit()
