from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=300)


class CentreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    location: str
    tests: list["TestOut"] = []


class TestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price: Decimal


class PatientDetails(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=100)
    gender: str = Field(min_length=1, max_length=50)
    height_cm: Decimal = Field(gt=0, le=300, max_digits=5, decimal_places=2)
    weight_kg: Decimal = Field(gt=0, le=500, max_digits=6, decimal_places=2)
    blood_group: str = Field(pattern="^(A|B|AB|O)[+-]$")


class BookingCreate(PatientDetails):
    test_id: int
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("appointment_at must include a timezone")
        return value


class BookingOut(PatientDetails):
    model_config = ConfigDict(from_attributes=True)
    id: int
    test_id: int
    appointment_at: datetime
    amount: Decimal
    status: str


class PaymentCreate(BaseModel):
    booking_id: int
    outcome: str | None = Field(default=None, pattern="^(SUCCESS|FAILED)$")


class WebhookEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    booking_id: int
    status: str = Field(pattern="^(SUCCESS|FAILED)$")
