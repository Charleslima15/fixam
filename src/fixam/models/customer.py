import uuid

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDPrimaryKey
from .enums import TrustTier


class Customer(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "customer"

    phone_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    phone_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    trust_tier: Mapped[TrustTier] = mapped_column(
        ENUM(TrustTier, name="trust_tier", create_type=False),
        nullable=False,
        server_default=TrustTier.new.value,
    )
    last_area_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quarter.id"), nullable=True
    )
