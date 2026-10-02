from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .auth import create_token, current_user, hash_password, verify_password
from .data_log import write_data_log
from .database import Base, engine, ensure_sqlite_booking_columns, get_db


Base.metadata.create_all(bind=engine)
ensure_sqlite_booking_columns()
app = FastAPI(title="EVE Healthcare API", version="0.1.0")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to the EVE Healthcare API! Assigment of : NIKHIL KUMAR YADAV"}

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/signup", response_model=schemas.Token, status_code=status.HTTP_201_CREATED)
def signup(payload: schemas.Credentials, database: Session = Depends(get_db)) -> schemas.Token:
    user = models.User(email=payload.email.lower(), password_hash=hash_password(payload.password))
    database.add(user)
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered")
    database.refresh(user)
    return schemas.Token(access_token=create_token(user.id))


@app.post("/auth/login", response_model=schemas.Token)
def login(payload: schemas.Credentials, database: Session = Depends(get_db)) -> schemas.Token:
    user = database.scalar(select(models.User).where(models.User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return schemas.Token(access_token=create_token(user.id))


@app.post("/centres", response_model=schemas.CentreOut, status_code=status.HTTP_201_CREATED)
def create_centre(payload: schemas.CentreCreate, _: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.Centre:
    centre = models.Centre(name=payload.name, location=payload.location)
    database.add(centre)
    database.commit()
    database.refresh(centre)
    return centre


@app.post("/centres/{centre_id}/tests", response_model=schemas.TestOut, status_code=status.HTTP_201_CREATED)
def create_test(centre_id: int, payload: schemas.TestCreate, _: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.DiagnosticTest:
    if database.get(models.Centre, centre_id) is None:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    test = models.DiagnosticTest(centre_id=centre_id, name=payload.name, price=payload.price)
    database.add(test)
    database.commit()
    database.refresh(test)
    return test


@app.get("/centres", response_model=list[schemas.CentreOut])
def list_centres(database: Session = Depends(get_db)) -> list[models.Centre]:
    return list(database.scalars(select(models.Centre).order_by(models.Centre.id)).unique())


@app.post("/bookings", response_model=schemas.BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(payload: schemas.BookingCreate, user: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.Booking:
    test = database.get(models.DiagnosticTest, payload.test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="Diagnostic test not found")
    appointment = payload.appointment_at
    if appointment <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Appointment must be in the future")
    booking = models.Booking(
        user_id=user.id,
        test_id=test.id,
        appointment_at=appointment,
        amount=test.price,
        name=payload.name,
        surname=payload.surname,
        gender=payload.gender,
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        blood_group=payload.blood_group,
    )
    database.add(booking)
    database.commit()
    database.refresh(booking)
    write_data_log("booking.created", booking)
    return booking


def owned_booking(booking_id: int, user: models.User, database: Session) -> models.Booking:
    booking = database.get(models.Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@app.get("/bookings", response_model=list[schemas.BookingOut])
def list_bookings(user: models.User = Depends(current_user), database: Session = Depends(get_db)) -> list[models.Booking]:
    return list(database.scalars(select(models.Booking).where(models.Booking.user_id == user.id).order_by(models.Booking.id)))


@app.get("/bookings/{booking_id}", response_model=schemas.BookingOut)
def get_booking(booking_id: int, user: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.Booking:
    return owned_booking(booking_id, user, database)


@app.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: int, user: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.Booking:
    booking = owned_booking(booking_id, user, database)
    if booking.status != models.BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending bookings can be cancelled")
    booking.status = models.BookingStatus.CANCELLED
    database.commit()
    database.refresh(booking)
    write_data_log("booking.cancelled", booking)
    return booking


@app.post("/payments", response_model=schemas.BookingOut)
def pay(payload: schemas.PaymentCreate, user: models.User = Depends(current_user), database: Session = Depends(get_db)) -> models.Booking:
    booking = owned_booking(payload.booking_id, user, database)
    if booking.status != models.BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Booking is no longer payable")
    outcome = payload.outcome or "SUCCESS"
    booking.status = models.BookingStatus.CONFIRMED if outcome == "SUCCESS" else models.BookingStatus.FAILED
    database.add(models.Payment(booking_id=booking.id, status=models.PaymentStatus(outcome)))
    database.commit()
    database.refresh(booking)
    write_data_log("payment.completed", booking)
    return booking


@app.post("/payments/webhook", response_model=schemas.BookingOut)
def payment_webhook(payload: schemas.WebhookEvent, database: Session = Depends(get_db)) -> models.Booking:
    existing = database.scalar(select(models.Payment).where(models.Payment.event_id == payload.event_id))
    if existing is not None:
        return existing.booking
    booking = database.get(models.Booking, payload.booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != models.BookingStatus.PENDING:
        raise HTTPException(status_code=409, detail="Booking is no longer payable")
    booking.status = models.BookingStatus.CONFIRMED if payload.status == "SUCCESS" else models.BookingStatus.FAILED
    database.add(models.Payment(booking_id=booking.id, event_id=payload.event_id, status=models.PaymentStatus(payload.status)))
    try:
        database.commit()
    except IntegrityError:
        database.rollback()
        existing = database.scalar(select(models.Payment).where(models.Payment.event_id == payload.event_id))
        if existing is not None:
            return existing.booking
        raise
    database.refresh(booking)
    write_data_log("payment.webhook.completed", booking)
    return booking
