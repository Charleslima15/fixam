import uuid

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDPrimaryKey


class Trade(Base, UUIDPrimaryKey):
    __tablename__ = "trade"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Quarter(Base, UUIDPrimaryKey):
    __tablename__ = "quarter"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class Provider(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "provider"

    phone_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    phone_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_suspended: Mapped[bool] = mapped_column(Boolean, server_default="false")
    suspend_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    trades: Mapped[list["ProviderTrade"]] = relationship(back_populates="provider")
    areas: Mapped[list["ProviderArea"]] = relationship(back_populates="provider")


class ProviderTrade(Base):
    __tablename__ = "provider_trade"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), primary_key=True
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trade.id"), primary_key=True
    )

    provider: Mapped[Provider] = relationship(back_populates="trades")


class ProviderArea(Base):
    __tablename__ = "provider_area"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("provider.id"), primary_key=True
    )
    quarter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quarter.id"), primary_key=True
    )

    provider: Mapped[Provider] = relationship(back_populates="areas")
