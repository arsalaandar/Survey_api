# SurveyApi architecture

Existing mobile routes stay unversioned and compatible; new capabilities use `/api/v1`. The legacy listing stays an array without query parameters. Paging or filtering opts into `{items, page, limit, total}`.

Passwords use bcrypt because its deliberately expensive work factor resists offline guessing; the SHA-256 verifier remains for migrated records. JWTs are appropriate for this stateless mobile API and preserve the existing claims contract.

PostGIS stores a derived `geography(Point,4326)` beside latitude/longitude. Its GiST index and `ST_DWithin` make nearby queries fast and geographically accurate. SQLite has a Haversine fallback exclusively for tests.

Alembic owns schemas: run `make migrate` before deploy. Request middleware provides a request ID and JSON-shaped logs. Sentry starts only when `SURVEY_SENTRY_DSN` is configured.
