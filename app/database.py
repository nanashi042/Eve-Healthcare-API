import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./eve_healthcare.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()


def ensure_sqlite_booking_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    columns = {column["name"] for column in inspect(engine).get_columns("bookings")}
    additions = {
        "name": "VARCHAR(100) NOT NULL DEFAULT 'Unknown'",
        "surname": "VARCHAR(100) NOT NULL DEFAULT 'Unknown'",
        "gender": "VARCHAR(50) NOT NULL DEFAULT 'unspecified'",
        "height_cm": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
        "weight_kg": "NUMERIC(6, 2) NOT NULL DEFAULT 0",
        "blood_group": "VARCHAR(3) NOT NULL DEFAULT 'O+'",
    }
    missing = ((column_name, column_definition) for column_name, column_definition in additions.items() if column_name not in columns)
    if not missing:
        return
    with engine.begin() as connection:
        for column_name, column_definition in missing:
            connection.execute(text(f'ALTER TABLE bookings ADD COLUMN "{column_name}" {column_definition}'))
