"""The journal's table: append-only, partitioned by month on ``at`` (docs/design/core-model.md, 9)."""

import datetime
import uuid
from typing import Any

from sqlalchemy import BigInteger, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from penaria.common.database import Base, Xid8

# Rows land here until monthly partitions are managed (pg-partsmith, with the worker).
DEFAULT_PARTITION = "journal_events_default"


class JournalEventDB(Base):
    __tablename__ = "journal_events"
    __table_args__ = (
        Index("journal_events_tx_seq_idx", "tx", "seq"),
        Index("journal_events_home_id_tx_seq_idx", "home_id", "tx", "seq"),
        Index("journal_events_entity_id_at_idx", "entity_id", "at"),
        {"postgresql_partition_by": "RANGE (at)"},
    )

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime.datetime] = mapped_column(primary_key=True)
    id: Mapped[uuid.UUID]
    home_id: Mapped[uuid.UUID]
    type: Mapped[str] = mapped_column(Text)
    version: Mapped[int]
    entity_id: Mapped[uuid.UUID | None]
    actor: Mapped[dict[str, Any]] = mapped_column(JSONB)
    command_id: Mapped[uuid.UUID | None]
    changeset_id: Mapped[uuid.UUID | None]
    tx: Mapped[int] = mapped_column(Xid8, server_default=text("pg_current_xact_id()"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
