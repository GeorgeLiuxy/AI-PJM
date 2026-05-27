"""Auth and project access tests."""

import pytest

from app.core.config import settings
from app.modules.auth.repository import auth_repository
from app.modules.auth.security import hash_password


@pytest.fixture()
def auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)


async def _create_user_with_project(
    db_session,
    *,
    username: str,
    password: str = "password123",
    role: str = "operator",
    project_key: str,
    project_name: str,
    project_role: str = "operator",
):
    user = await auth_repository.create_user(
        db=db_session,
        username=username,
        display_name=username.title(),
        password_hash=hash_password(password),
        role=role,
    )
    project = await auth_repository.create_project(
        db=db_session,
        key=project_key,
        name=project_name,
    )
    await auth_repository.create_project_member(
        db=db_session,
        user_id=user.id,
        project_id=project.id,
        role=project_role,
    )
    await db_session.commit()
    return user, project


async def _login(client, username: str, password: str = "password123") -> str:
    response = await client.post(
        "/api/v2/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_auth_me_returns_local_principal_when_auth_disabled(client):
    response = await client.get("/api/v2/auth/me")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["auth_enabled"] is False
    assert payload["role"] == "admin"


@pytest.mark.asyncio
async def test_delivery_requires_token_when_auth_enabled(client, auth_enabled):
    response = await client.get("/api/v2/demands")

    assert response.status_code == 401
    assert response.json()["message"] == "Authentication required"


@pytest.mark.asyncio
async def test_operator_can_create_demand_in_own_project(client, db_session, auth_enabled):
    _, project = await _create_user_with_project(
        db_session,
        username="operator",
        project_key="alpha",
        project_name="Alpha",
    )
    token = await _login(client, "operator")

    response = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {token}"},
        json={"raw_input": "Add a compact status badge.", "project_id": project.id},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["project_id"] == project.id
    assert payload["created_by_user_id"] is not None
    assert payload["requester_ref"] == "operator"


@pytest.mark.asyncio
async def test_project_permissions_filter_delivery_records(client, db_session, auth_enabled):
    _, alpha = await _create_user_with_project(
        db_session,
        username="alpha_user",
        project_key="alpha",
        project_name="Alpha",
    )
    _, beta = await _create_user_with_project(
        db_session,
        username="beta_user",
        project_key="beta",
        project_name="Beta",
    )
    alpha_token = await _login(client, "alpha_user")
    beta_token = await _login(client, "beta_user")

    created = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {alpha_token}"},
        json={"raw_input": "Alpha only change.", "project_id": alpha.id},
    )
    assert created.status_code == 201
    demand_id = created.json()["data"]["id"]

    list_response = await client.get(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["data"] == []

    detail_response = await client.get(
        f"/api/v2/demands/{demand_id}",
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert detail_response.status_code == 403

    forbidden_create = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {alpha_token}"},
        json={"raw_input": "Cross project change.", "project_id": beta.id},
    )
    assert forbidden_create.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_read_but_cannot_create_demand(client, db_session, auth_enabled):
    _, project = await _create_user_with_project(
        db_session,
        username="viewer",
        role="viewer",
        project_key="read",
        project_name="Read Only",
        project_role="viewer",
    )
    token = await _login(client, "viewer")

    list_response = await client.get(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200

    create_response = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {token}"},
        json={"raw_input": "Viewer should not write.", "project_id": project.id},
    )
    assert create_response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_projects_and_users(client, db_session, auth_enabled):
    _, project = await _create_user_with_project(
        db_session,
        username="admin_user",
        role="admin",
        project_key="admin-project",
        project_name="Admin Project",
        project_role="owner",
    )
    token = await _login(client, "admin_user")

    projects_response = await client.get(
        "/api/v2/auth/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert projects_response.status_code == 200
    projects = projects_response.json()["data"]
    assert projects[0]["id"] == project.id
    assert projects[0]["key"] == "admin-project"

    users_response = await client.get(
        "/api/v2/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert users_response.status_code == 200
    users = users_response.json()["data"]
    assert users[0]["username"] == "admin_user"
    assert users[0]["projects"][0]["role"] == "owner"


@pytest.mark.asyncio
async def test_non_admin_cannot_list_managed_users(client, db_session, auth_enabled):
    await _create_user_with_project(
        db_session,
        username="plain_operator",
        project_key="plain-project",
        project_name="Plain Project",
    )
    token = await _login(client, "plain_operator")

    response = await client.get(
        "/api/v2/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delivery_actions_create_project_scoped_audit_events(client, db_session, auth_enabled):
    _, alpha = await _create_user_with_project(
        db_session,
        username="alpha_auditor",
        project_key="audit-alpha",
        project_name="Audit Alpha",
    )
    _, beta = await _create_user_with_project(
        db_session,
        username="beta_auditor",
        project_key="audit-beta",
        project_name="Audit Beta",
    )
    alpha_token = await _login(client, "alpha_auditor")
    beta_token = await _login(client, "beta_auditor")

    created = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {alpha_token}"},
        json={"raw_input": "Audit this demand.", "project_id": alpha.id},
    )
    assert created.status_code == 201
    demand_id = created.json()["data"]["id"]

    alpha_events = await client.get(
        "/api/v2/audit/events",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert alpha_events.status_code == 200
    event_payload = alpha_events.json()["data"]
    assert event_payload[0]["action"] == "delivery.demand_created"
    assert event_payload[0]["project_id"] == alpha.id
    assert event_payload[0]["entity_type"] == "demand"
    assert event_payload[0]["entity_id"] == demand_id
    assert event_payload[0]["actor_ref"] == "alpha_auditor"

    beta_events = await client.get(
        "/api/v2/audit/events",
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert beta_events.status_code == 200
    assert beta_events.json()["data"] == []

    forbidden_project_events = await client.get(
        f"/api/v2/audit/events?project_id={beta.id}",
        headers={"Authorization": f"Bearer {alpha_token}"},
    )
    assert forbidden_project_events.status_code == 403
