from sqlalchemy import create_engine, inspect

from app.db.base import Base
from app.db import models  # noqa: F401


def test_schema_builds_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {
        "users",
        "support_messages",
        "moderator_participants",
        "moderator_sessions",
        "moderator_view_messages",
        "audit_logs",
    } <= names
