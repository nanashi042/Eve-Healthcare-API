import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from . import models, schemas


EventName = Literal[
    "booking.created",
    "booking.cancelled",
    "payment.completed",
    "payment.webhook.completed",
]


class DataLogEntry(BaseModel):
    event: EventName
    recorded_at: datetime
    booking_id: int
    status: models.BookingStatus
    patient: schemas.PatientDetails


def write_data_log(event: EventName, booking: models.Booking) -> None:
    entry = DataLogEntry(
        event=event,
        recorded_at=datetime.now(timezone.utc),
        booking_id=booking.id,
        status=booking.status,
        patient=schemas.PatientDetails.model_validate(booking, from_attributes=True),
    )
    path = Path(os.getenv("DATA_LOG_PATH", "eve_healthcare_data.jsonl"))
    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(entry.model_dump_json() + "\n")