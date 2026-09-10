from .conftest import admin_headers, payload, register, surveyor_headers, token


# ---------------------------------------------------------------------------
# Registration (admin-gated)
# ---------------------------------------------------------------------------

def test_register_requires_admin_token(client):
    """No token at all -> 401, not 403. This is the bug the old test suite
    was hiding: it called register() with zero auth and expected success."""
    response = register(client, headers={}, username="surveyor")
    assert response.status_code == 401


def test_register_rejects_non_admin_token(client):
    surveyor = surveyor_headers(client, "surveyor1")
    response = register(client, headers=surveyor, username="surveyor2")
    assert response.status_code == 403


def test_register_succeeds_for_admin_and_duplicate_username_is_rejected(client):
    admin = admin_headers(client)
    assert register(client, admin, username="alice").status_code == 200
    assert register(client, admin, username="alice").status_code == 400


def test_register_defaults_to_surveyor_role_when_role_omitted(client):
    admin = admin_headers(client)
    register(client, admin, username="norole")
    surveyor = token(client, "norole", "secret")
    # A Surveyor can't hit the admin-only register route.
    assert register(client, surveyor, username="x").status_code == 403


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success_wrong_password_and_missing_user(client):
    admin = admin_headers(client)
    register(client, admin, username="surveyor")
    assert client.post("/api/Auth/login", json={"username": "surveyor", "password": "secret"}).status_code == 200
    assert client.post("/api/Auth/login", json={"username": "surveyor", "password": "nope"}).status_code == 401
    assert client.post("/api/Auth/login", json={"username": "nobody", "password": "nope"}).status_code == 401


def test_login_response_does_not_leak_password_hash(client):
    admin = admin_headers(client)
    register(client, admin, username="surveyor")
    body = client.post("/api/Auth/login", json={"username": "surveyor", "password": "secret"}).json()
    assert "password" not in body and "password_hash" not in body


# ---------------------------------------------------------------------------
# Survey submission, auth requirements, photo validation
# ---------------------------------------------------------------------------

def test_submit_requires_auth_and_validates_photo(client):
    assert client.post("/api/Survey", json=payload()).status_code == 401
    headers = surveyor_headers(client)
    assert client.post("/api/Survey", json=payload(photo="aGVsbG8="), headers=headers).status_code == 400
    assert client.post("/api/Survey", json=payload(), headers=headers).status_code == 200


def test_list_scope_pagination_and_delete_permissions(client):
    admin = admin_headers(client)
    surveyor = surveyor_headers(client, admin=admin)
    saved = client.post("/api/Survey", json=payload(), headers=surveyor).json()["id"]
    assert len(client.get("/api/Survey", headers=surveyor).json()) == 1
    paged = client.get("/api/Survey?page=1&limit=20&community=A", headers=admin).json()
    assert paged["total"] == 1 and len(paged["items"]) == 1
    assert client.delete(f"/api/Survey/{saved}", headers=surveyor).status_code == 403
    assert client.delete(f"/api/Survey/{saved}", headers=admin).status_code == 200


def test_nearby_search(client):
    headers = surveyor_headers(client)
    client.post("/api/Survey", json=payload(), headers=headers)
    client.post("/api/Survey", json=payload(latitude=19.0760, longitude=72.8777), headers=headers)
    response = client.get("/api/v1/Survey/nearby?lat=28.6139&lng=77.2090&radius_km=2", headers=headers)
    assert response.status_code == 200 and len(response.json()) == 1
    assert response.json()[0]["distanceKm"] == 0


def test_single_submit_is_idempotent_when_client_id_is_present(client):
    headers = surveyor_headers(client)
    body = payload(clientId="0c17c87e-7b67-4f9e-bc3d-dc3a654d9bc6")
    first = client.post("/api/Survey", json=body, headers=headers).json()
    second = client.post("/api/Survey", json=body, headers=headers).json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/Survey", headers=headers).json()) == 1


def test_batch_reports_created_duplicate_and_bad_items_independently(client):
    headers = surveyor_headers(client)
    good = payload(clientId="e62908c2-8e6f-48d5-a2f2-a621322bf0a2")
    results = client.post("/api/Survey/batch", json=[good, good, {"clientId": "bad"}], headers=headers).json()
    assert [item["status"] for item in results] == ["created", "already_synced", "error"]
    assert results[0]["id"] == results[1]["id"]


def test_batch_item_missing_client_id_reports_error_not_500(client):
    """A structurally valid survey (passes SurveyDto validation) but with no
    clientId at all -- batch sync requires it for idempotent retries."""
    headers = surveyor_headers(client)
    valid_but_no_client_id = payload()  # no clientId key
    results = client.post("/api/Survey/batch", json=[valid_but_no_client_id], headers=headers).json()
    assert results[0]["status"] == "error"
    assert "clientId" in results[0]["message"]


def test_deleting_survey_with_photo_removes_the_uploaded_file(client):
    import base64
    admin = admin_headers(client)
    headers = surveyor_headers(client, admin=admin)
    jpeg = base64.b64encode(b"\xff\xd8\xff" + b"0" * 20).decode()
    created = client.post("/api/Survey", json=payload(photo=jpeg), headers=headers).json()
    file_path = client.upload_dir / created["photoUrl"].removeprefix("/uploads/")
    assert file_path.exists()
    client.delete(f"/api/Survey/{created['id']}", headers=admin)
    assert not file_path.exists()