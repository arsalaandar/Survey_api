# SurveyApi (FastAPI port)          |
|--------------------------|--------------------------|
| `POST /api/Auth/register`| same |
| `POST /api/Auth/login`   | same |
| `POST /api/Survey`       | same (JWT required) |
| `GET /api/Survey`        | same (JWT required) |
| `DELETE /api/Survey/{id}`| same (JWT + admin role required) |
| `GET /api/v1/Survey/nearby` | new nearby search (JWT required) |
| `/uploads/{file}`        | same (static file serving) |

Auth: send `Authorization: Bearer <token>` exactly as before.

Registration and login are limited to five requests per minute per IP. Nearby
search takes `lat`, `lng`, and optional `radius_km`, and returns distance-ordered
results with `distanceKm`.

## Testing

53 tests, 88% coverage, run against an isolated in-memory SQLite DB (no
Postgres required). Run them with:

```bash
pytest tests/ -v
# with coverage:
pytest tests/ --cov=app --cov-report=term-missing
```

`tests/test_api.py` covers core behavior: registration, login, survey
submission, pagination, ownership scoping, nearby search, idempotent/batch
sync, and admin-only delete.

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
  `429` after 5 requests/minute, not just that the decorator is present.

Two gaps are intentionally documented as passing tests rather than silently
left alone: survey `latitude`/`longitude` have no range validation (unlike
the `/nearby` endpoint's `lat`/`lng`, which do), and text fields accept
empty strings. Both are cheap to tighten later if needed.

## Local development

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # then edit .env with your real DB/JWT values

uvicorn app.main:app --reload --port 8000
```

Before running a new or upgraded Postgres database, apply schema changes with
`make migrate` (or `alembic upgrade head`). Docker Compose now uses PostGIS.

Interactive docs (Swagger equivalent) are at `http://localhost:8000/docs`.

## Existing data / existing users

- Your existing Postgres database (`survey_db`) can be reused as-is — the
  SQLAlchemy models create the same `users` and `surveys` tables/columns if
  they don't already exist, and won't touch existing rows.
- **Password hashing was upgraded from SHA-256 to bcrypt** (SHA-256 alone is
  not considered safe for password storage). Existing users' old SHA-256
  hashes still work — `verify_password()` detects the old format and falls
  back to it automatically, so nobody needs to reset their password. New
  registrations get bcrypt hashes going forward.

## What changed vs. the original API (and why)

- **Password hashing**: bcrypt instead of raw SHA-256 (see above).
- **Secrets**: the original `appsettings.json` had the DB password and JWT
  signing key committed in plaintext. In this version, all of that comes from
  environment variables / `.env` (see `.env.example`) — **do not commit your
  real `.env`**.
- **CORS**: the original allowed any origin. That's kept as the default for
  compatibility with your Flutter app, but you should set
  `SURVEY_ALLOWED_ORIGINS` to your actual app's origin(s) once you know them
  (mobile apps calling directly via HTTP don't send an `Origin` header, so
  this mainly matters if you ever add a web frontend/admin panel).

## Production deployment

### Option A: Docker Compose (recommended, simplest)

1. On your server, install Docker + Docker Compose.
2. Copy this whole project to the server.
3. Create `.env` from `.env.example`, filling in a strong `SURVEY_JWT_SECRET`
   and a real `POSTGRES_PASSWORD`, and matching that password in
   `SURVEY_DATABASE_URL` (host should be `db`, matching the compose service
   name).
4. Edit `nginx.conf` and set `server_name` to your real domain.
5. Start everything:
   ```bash
   docker compose up -d --build
   ```
6. Add HTTPS (strongly recommended — you're sending JWTs and photos):
   ```bash
   sudo apt install certbot
   sudo certbot certonly --standalone -d your-domain.com
   ```
   Then mount the cert into nginx and uncomment the `443` port + TLS volume
   in `docker-compose.yml`, and add a `listen 443 ssl;` server block to
   `nginx.conf` pointing at `/etc/letsencrypt/live/your-domain.com/`.
7. Point your Flutter app's base URL at `https://your-domain.com`.

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

- [ ] `SURVEY_JWT_SECRET` is a long random value, different from the one in
      the old `appsettings.json` (that one is now exposed since it was in
      your uploaded files).
- [ ] Database password is changed from `12345`.
- [ ] HTTPS is enabled — right now tokens and photos would otherwise travel
      in plaintext.
- [ ] `SURVEY_ALLOWED_ORIGINS` narrowed down from `*` if you add any browser
      based client.
- [ ] Run `alembic upgrade head` before starting the updated API.
- [ ] Exercise legacy login, submit, unfiltered list, and admin delete from
      Flutter; those unversioned paths remain its compatibility contract.
- [ ] Set `SURVEY_ENVIRONMENT=production`, a real JWT secret, and restricted
      origins. Optionally set `SURVEY_SENTRY_DSN` for error reporting.