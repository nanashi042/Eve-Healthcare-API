# EVE Healthcare API

This project is a small backend for booking diagnostic tests and simulating the payment flow around those bookings. It was built for the EVE SDE backend assignment, with the focus on clear API behavior, sensible data modeling, authentication, and the edge cases that tend to cause trouble in booking systems.

## What is included

- User signup and login with JWT bearer authentication
- Diagnostic centres and the tests offered by each centre
- Authenticated booking creation and booking history
- Booking states: `PENDING`, `CONFIRMED`, `FAILED`, and `CANCELLED`
- Simulated successful and failed payments
- An idempotent payment webhook
- Ownership checks for viewing, paying for, and cancelling bookings
- Validation for invalid payloads, future appointments, prices, and payment outcomes
- Pydantic patient-data validation and structured JSON Lines lifecycle logging
- SQLite for local development, with SQLAlchemy support for PostgreSQL
- OpenAPI documentation through FastAPI
- Integration tests covering the main flow and failure cases

## Running the project

This project uses `uv` for dependency management.

```bash
uv sync --dev
uv run uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

Useful links:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `http://127.0.0.1:8000/health`

By default, the application creates `eve_healthcare.db` in the project directory. A different database can be selected with `DATABASE_URL`. Set `SECRET_KEY` to a long random value when running outside a local development environment.

## Typical workflow

Protected endpoints expect this header:

```text
Authorization: Bearer <access_token>
```

### 1. Create an account

```bash
curl -X POST http://127.0.0.1:8000/auth/signup \
	-H 'Content-Type: application/json' \
	-d '{"email":"patient@example.com","password":"password123"}'
```

The response contains an `access_token`. Store it in a shell variable for the remaining requests:

```bash
TOKEN="<access_token returned above>"
```

### 2. Create a centre and diagnostic test

Centre and test creation requires authentication in this assignment.

```bash
curl -X POST http://127.0.0.1:8000/centres \
	-H "Authorization: Bearer $TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{"name":"EVE Central","location":"London"}'
```

Then add a test using the returned centre ID:

```bash
curl -X POST http://127.0.0.1:8000/centres/1/tests \
	-H "Authorization: Bearer $TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{"name":"Complete Blood Count","price":"25.00"}'
```

`GET /centres` returns each centre together with its available tests and prices.

### 3. Create a booking

Appointments must be in the future and include a timezone. The test price is copied onto the booking when it is created, so changing the catalogue later does not change an existing booking.

```bash
curl -X POST http://127.0.0.1:8000/bookings \
	-H "Authorization: Bearer $TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{
		"test_id": 1,
		"appointment_at": "2030-01-15T10:00:00+00:00",
		"name": "Alex",
		"surname": "Patient",
		"gender": "prefer_not_to_say",
		"height_cm": 175,
		"weight_kg": 70,
		"blood_group": "O+"
	}'
```

Use `GET /bookings` to list the current user's bookings or `GET /bookings/{booking_id}` to retrieve one booking.

### 4. Simulate payment

The mock payment endpoint accepts either `SUCCESS` or `FAILED` and updates the booking accordingly.

```bash
curl -X POST http://127.0.0.1:8000/payments \
	-H "Authorization: Bearer $TOKEN" \
	-H 'Content-Type: application/json' \
	-d '{"booking_id":1,"outcome":"SUCCESS"}'
```

Only the booking owner can make a payment. A booking that is already paid, failed, or cancelled cannot be paid again.

### 5. Process a payment webhook

The webhook represents a callback from a simulated payment provider:

```bash
curl -X POST http://127.0.0.1:8000/payments/webhook \
	-H 'Content-Type: application/json' \
	-d '{"event_id":"evt_1001","booking_id":1,"status":"SUCCESS"}'
```

`event_id` is unique. Sending the same event more than once returns the existing booking and does not create another payment. A new event cannot overwrite a booking that has already reached a terminal state.

## API reference

| Method | Endpoint | Purpose | Auth |
| --- | --- | --- | --- |
| `POST` | `/auth/signup` | Create an account | No |
| `POST` | `/auth/login` | Log in and receive a JWT | No |
| `GET` | `/centres` | List centres and tests | No |
| `POST` | `/centres` | Create a centre | Yes |
| `POST` | `/centres/{centre_id}/tests` | Add a test to a centre | Yes |
| `POST` | `/bookings` | Create a booking | Yes |
| `GET` | `/bookings` | List the current user's bookings | Yes |
| `GET` | `/bookings/{booking_id}` | Read one owned booking | Yes |
| `POST` | `/bookings/{booking_id}/cancel` | Cancel an owned pending booking | Yes |
| `POST` | `/payments` | Simulate a payment | Yes |
| `POST` | `/payments/webhook` | Apply a provider payment event | No* |

\* The webhook is intentionally unauthenticated because it represents an external provider callback. A production integration should verify the provider's signature before processing the request.

## Data model

The database has five main tables:

- `users` stores a normalized, unique email address and a salted PBKDF2 password hash.
- `centres` stores the diagnostic centre name and location.
- `diagnostic_tests` belongs to a centre and stores the current catalogue price.
- `bookings` links a user to a test and stores the appointment time, booking amount, and status.
- `payments` links payment attempts to bookings. Webhook events use a unique `event_id` to make retries safe.

The booking amount is deliberately stored separately from the test price. That preserves the amount agreed at booking time even if the test price changes later.

Patient details are defined once in the Pydantic `PatientDetails` model and reused for booking input, booking output, and the data log. Successful booking, cancellation, direct payment, and webhook events are appended to `eve_healthcare_data.jsonl` as validated JSON records. Set `DATA_LOG_PATH` to choose another log location. Passwords, JWTs, and authentication headers are never written to this log.

## Error handling and authorization

- Invalid JSON, invalid enum values, invalid prices, short passwords, and timezone-less appointments return `422`.
- Missing centres, tests, and bookings return `404`.
- Users cannot inspect or modify another user's bookings.
- Duplicate email registration returns `409`.
- Payments and cancellations are allowed only while a booking is `PENDING`.
- Repeated webhook delivery is idempotent.
- A different webhook event cannot change an already completed, failed, or cancelled booking.

## Tests

Run the test suite with:

```bash
uv run pytest
```

The tests cover signup, booking and payment flow, webhook idempotency, invalid requests, duplicate signup, failed payments, invalid booking IDs, unauthorized access, cancellation, and conflicting webhook events.

## Design notes

SQLite keeps the project easy to run locally, while SQLAlchemy allows the same application to use PostgreSQL through `DATABASE_URL`. Centre and test management is authenticated but does not include staff roles because role management is outside the scope of this assignment. Database migrations, signed provider webhooks, rate limiting, pagination, structured logging, and background jobs would be the next additions for a production deployment.
