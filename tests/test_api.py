from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def auth(email: str) -> dict[str, str]:
    response = client.post("/auth/signup", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_booking_payment_and_idempotent_webhook() -> None:
    headers = auth("patient@example.com")
    centre = client.post("/centres", headers=headers, json={"name": "EVE Central", "location": "London"}).json()
    test = client.post(f"/centres/{centre['id']}/tests", headers=headers, json={"name": "CBC", "price": "25.00"}).json()
    booking = client.post(
        "/bookings",
        headers=headers,
        json={
            "test_id": test["id"],
            "appointment_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "name": "Alex",
            "surname": "Patient",
            "gender": "prefer_not_to_say",
            "height_cm": "175.00",
            "weight_kg": "70.00",
            "blood_group": "O+",
        },
    ).json()

    assert booking["name"] == "Alex"
    assert booking["surname"] == "Patient"
    assert booking["gender"] == "prefer_not_to_say"
    assert booking["height_cm"] == "175.00"
    assert booking["weight_kg"] == "70.00"
    assert booking["blood_group"] == "O+"

    webhook = {"event_id": "evt_1", "booking_id": booking["id"], "status": "SUCCESS"}
    first = client.post("/payments/webhook", json=webhook)
    second = client.post("/payments/webhook", json=webhook)

    assert first.status_code == 200
    assert first.json()["status"] == "CONFIRMED"
    assert second.status_code == 200
    assert second.json()["id"] == booking["id"]


def test_users_cannot_read_each_others_bookings() -> None:
    owner_headers = auth("owner@example.com")
    other_headers = auth("other@example.com")
    centre = client.post("/centres", headers=owner_headers, json={"name": "EVE", "location": "Leeds"}).json()
    test = client.post(f"/centres/{centre['id']}/tests", headers=owner_headers, json={"name": "MRI", "price": "100.00"}).json()
    booking = client.post(
        "/bookings",
        headers=owner_headers,
        json={
            "test_id": test["id"],
            "appointment_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "name": "Owner",
            "surname": "Patient",
            "gender": "female",
            "height_cm": "165.00",
            "weight_kg": "60.00",
            "blood_group": "A+",
        },
    ).json()

    response = client.get(f"/bookings/{booking['id']}", headers=other_headers)
    assert response.status_code == 404


def create_booking(headers: dict[str, str], email_suffix: str = "") -> dict:
    centre = client.post(
        "/centres",
        headers=headers,
        json={"name": f"EVE {email_suffix}", "location": "London"},
    ).json()
    diagnostic_test = client.post(
        f"/centres/{centre['id']}/tests",
        headers=headers,
        json={"name": "CBC", "price": "25.00"},
    ).json()
    return client.post(
        "/bookings",
        headers=headers,
        json={
            "test_id": diagnostic_test["id"],
            "appointment_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "name": "Test",
            "surname": "Patient",
            "gender": "male",
            "height_cm": "180.00",
            "weight_kg": "80.00",
            "blood_group": "B+",
        },
    ).json()


def test_invalid_requests_and_duplicate_signup_are_rejected() -> None:
    response = client.post("/auth/signup", json={"email": "duplicate@example.com", "password": "password123"})
    assert response.status_code == 201
    duplicate = client.post("/auth/signup", json={"email": "DUPLICATE@example.com", "password": "password123"})
    assert duplicate.status_code == 409

    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    naive_booking = client.post(
        "/bookings",
        headers=headers,
        json={"test_id": 999, "appointment_at": "2030-01-01T12:00:00"},
    )
    assert naive_booking.status_code == 422

    missing_booking = client.post("/payments", headers=headers, json={"booking_id": 999, "outcome": "SUCCESS"})
    assert missing_booking.status_code == 404


def test_failed_payment_is_final_and_payment_requires_booking_owner() -> None:
    owner_headers = auth("payer@example.com")
    other_headers = auth("not-payer@example.com")
    booking = create_booking(owner_headers, "payer")

    unauthorized = client.post(
        "/payments",
        headers=other_headers,
        json={"booking_id": booking["id"], "outcome": "SUCCESS"},
    )
    assert unauthorized.status_code == 404

    failed = client.post(
        "/payments",
        headers=owner_headers,
        json={"booking_id": booking["id"], "outcome": "FAILED"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "FAILED"

    retry = client.post(
        "/payments",
        headers=owner_headers,
        json={"booking_id": booking["id"], "outcome": "SUCCESS"},
    )
    assert retry.status_code == 409


def test_cancellation_requires_owner_and_pending_booking() -> None:
    owner_headers = auth("canceller@example.com")
    other_headers = auth("observer@example.com")
    booking = create_booking(owner_headers, "canceller")

    unauthorized = client.post(f"/bookings/{booking['id']}/cancel", headers=other_headers)
    assert unauthorized.status_code == 404

    cancelled = client.post(f"/bookings/{booking['id']}/cancel", headers=owner_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    repeated = client.post(f"/bookings/{booking['id']}/cancel", headers=owner_headers)
    assert repeated.status_code == 409


def test_webhook_cannot_change_a_completed_booking_with_a_new_event() -> None:
    headers = auth("webhook-owner@example.com")
    booking = create_booking(headers, "webhook")
    first = client.post(
        "/payments/webhook",
        json={"event_id": "evt_success", "booking_id": booking["id"], "status": "SUCCESS"},
    )
    assert first.status_code == 200

    conflicting = client.post(
        "/payments/webhook",
        json={"event_id": "evt_failed", "booking_id": booking["id"], "status": "FAILED"},
    )
    assert conflicting.status_code == 409
