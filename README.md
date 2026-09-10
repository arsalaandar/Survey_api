# SurveyApi

A FastAPI backend for a field-survey mobile app: JWT-based auth with
Surveyor/Admin roles, PostGIS-backed geospatial search, offline-friendly
idempotent sync, and photo uploads.

## API routes

| Route | Notes |
|---|---|
| `POST /api/Auth/register` | admin-only (requires an admin JWT) |
| `POST /api/Auth/login` | public |
| `POST /api/Survey` | JWT required |
| `GET /api/Survey` | JWT required |
| `DELETE /api/Survey/{id}` | JWT + admin role required |
| `GET /api/v1/Survey/nearby` | JWT required |
| `/uploads/{file}` | static file serving |

Auth: send `Authorization: Bearer <token>`.

Registration and login are limited to five requests per minute per IP.
Nearby search takes `lat`, `lng`, and optional `radius_km`, and returns
distance-ordered results with `distanceKm`.

## Testing

53 tests, 88% coverage, run against an isolated in-memory SQLite DB (no
Postgres required). Run them with:

```bash
pytest tests/ -v
# with coverage:
pytest tests/ --cov=app --cov-report=term-missing
```

`tests/test_api.py` covers core behavior: registration, login, survey
submission, pagination, ownership scoping, nearby search,
idempotent/batch sync, and admin-only delete.

`tests/test_security.py` targets the things that actually cause breaches in
JWT-based APIs, not just happy-path CRUD:

- **JWT attacks** — signature forged with the wrong secret, tampered role
  claims, the classic `alg=none` confusion attack, expired tokens, wrong
  issuer, malformed/missing tokens, and a token referencing a deleted user
  (fails safe, doesn't 500).
- **IDOR** — one Surveyor can't read, list, or delete another Surveyor's
  submissions; only Admin can.
- **Injection** — SQLi-style strings, `<script>` tags, template-injection
  and JNDI-style payloads are all round-tripped as inert literal text,
  proving the ORM's parameterization holds rather than assuming it does.
- **File upload abuse** — non-image bytes, fake `data:` URI smuggling,
  oversized payloads, and confirms uploaded filenames are always
  server-generated (no path-traversal surface from client input).
- **Password handling** — bcrypt round-trip, the legacy SHA-256 migration
  path, and confirms no response ever leaks a password hash.
- **Rate limiting** — confirms `/register` and `/login` actually return
  429 after 5 requests/minute, not just that the decorator is present.

Two gaps are intentionally documented as passing tests rather than silently
left alone: survey latitude/longitude have no range validation (unlike the
`/nearby` endpoint's `lat`/`lng`, which do), and text fields accept empty
strings. Both are cheap to tighten later if needed.

## Local development

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then edit .env with your real DB/JWT values

uvicorn app.main:app --reload --port 8000
```

Before running against a new or upgraded Postgres database, apply schema
changes with `make migrate` (or `alembic upgrade head`). Docker Compose uses
PostGIS.

Interactive docs (Swagger) are at `http://localhost:8000/docs`.

## Account creation

`POST /api/Auth/register` requires an existing Admin's token — there's no
public self-registration. To bootstrap the very first admin account on a
fresh database, run the seed script directly against the database (see
`scripts_create_admin.py` or run it inside the container with
`docker compose exec api python scripts_create_admin.py`).

## Security notes

- **Password hashing**: bcrypt. A legacy SHA-256 fallback exists in
  `verify_password()` for any rows created before this was adopted, so
  existing users don't need to reset their password.
- **Secrets**: JWT signing key and DB credentials come from environment
  variables / `.env` — **never commit your real `.env`**.
- **CORS**: set `SURVEY_ALLOWED_ORIGINS` to your actual origin(s) — the app
  refuses to start in production mode with a wildcard `*`.

## Production deployment

### Option A: Docker Compose (recommended, simplest)

1. On your server, install Docker + Docker Compose.
2. Copy this whole project to the server.
3. Create `.env` from `.env.example`, filling in a strong `SURVEY_JWT_SECRET`
   and a real `POSTGRES_PASSWORD`, and matching that password in
   `SURVEY_DATABASE_URL` (host should be `db`, matching the compose service
   name).
4. Edit `nginx.conf` and set `server_name` to your real domain (or `_` to
   accept any hostname/IP if you don't have a domain yet).
5. Start everything:
   ```bash
   docker compose up -d --build
   ```
6. Run migrations:
   ```bash
   docker compose exec api alembic upgrade head
   ```
7. Add HTTPS (strongly recommended — you're sending JWTs and photos):
   ```bash
   sudo apt install certbot
   sudo certbot certonly --standalone -d your-domain.com
   ```
   Then mount the cert into nginx and uncomment the `443` port + TLS volume
   in `docker-compose.yml`, and add a `listen 443 ssl;` server block to
   `nginx.conf` pointing at `/etc/letsencrypt/live/your-domain.com/`.
8. Point your Flutter app's base URL at your server's address.

### Option B: Bare-metal / VM with systemd

1. `pip install -r requirements.txt` inside a venv on the server.
2. Set environment variables (via `/etc/environment`, a systemd
   `EnvironmentFile`, or your process manager) instead of a `.env` file.
3. Run behind Gunicorn + Uvicorn workers:
   ```bash
   gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000
   ```
4. Put nginx (or Caddy) in front for TLS termination, exactly as in
   `nginx.conf`, pointing `proxy_pass` at `http://127.0.0.1:8000`.
5. Wrap step 3 in a systemd unit so it restarts on crash/reboot.

### Before you go live, double check

- [ ] `SURVEY_JWT_SECRET` is a long random value, unique to this deployment.
- [ ] Database password is a real, strong value.
- [ ] HTTPS is enabled — otherwise tokens and photos travel in plaintext.
- [ ] `SURVEY_ALLOWED_ORIGINS` is set to a real value, not `*`.
- [ ] `alembic upgrade head` has been run before starting the API.
- [ ] Exercise login, submit, list, and admin delete from the Flutter app
      end-to-end against the deployed server.
- [ ] `SURVEY_ENVIRONMENT=production` is set, along with a real JWT secret
      and restricted origins. Optionally set `SURVEY_SENTRY_DSN` for error
      reporting.
