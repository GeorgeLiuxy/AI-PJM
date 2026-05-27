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
async def test_admin_can_update_user_reset_password_and_manage_membership(client, db_session, auth_enabled):
    await _create_user_with_project(
        db_session,
        username="access_admin",
        role="admin",
        project_key="access-admin-project",
        project_name="Access Admin Project",
        project_role="owner",
    )
    managed_user = await auth_repository.create_user(
        db=db_session,
        username="managed_operator",
        display_name="Managed Operator",
        email="managed@example.com",
        password_hash=hash_password("old-password"),
        role="operator",
    )
    project = await auth_repository.create_project(
        db_session,
        key="managed-project",
        name="Managed Project",
    )
    await db_session.commit()
    token = await _login(client, "access_admin")

    updated = await client.patch(
        f"/api/v2/auth/users/{managed_user.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "display_name": "Managed Reviewer",
            "email": "reviewer@example.com",
            "role": "reviewer",
            "status": "active",
        },
    )
    assert updated.status_code == 200
    updated_data = updated.json()["data"]
    assert updated_data["display_name"] == "Managed Reviewer"
    assert updated_data["email"] == "reviewer@example.com"
    assert updated_data["role"] == "reviewer"

    membership = await client.put(
        f"/api/v2/auth/users/{managed_user.id}/memberships",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_id": project.id, "role": "owner"},
    )
    assert membership.status_code == 200
    membership_data = membership.json()["data"]
    assert membership_data["projects"][0]["id"] == project.id
    assert membership_data["projects"][0]["role"] == "owner"

    reset = await client.post(
        f"/api/v2/auth/users/{managed_user.id}/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "new-password"},
    )
    assert reset.status_code == 200
    old_login = await client.post(
        "/api/v2/auth/login",
        json={"username": "managed_operator", "password": "old-password"},
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v2/auth/login",
        json={"username": "managed_operator", "password": "new-password"},
    )
    assert new_login.status_code == 200

    removed = await client.delete(
        f"/api/v2/auth/users/{managed_user.id}/memberships/{project.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert removed.status_code == 200
    assert removed.json()["data"]["projects"] == []

    audit = await client.get(
        "/api/v2/audit/events?action=auth.user_updated",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit.status_code == 200
    assert audit.json()["data"][0]["entity_type"] == "user"


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_users(client, db_session, auth_enabled):
    operator, _ = await _create_user_with_project(
        db_session,
        username="access_operator",
        project_key="access-operator-project",
        project_name="Access Operator Project",
    )
    token = await _login(client, "access_operator")

    response = await client.patch(
        f"/api/v2/auth/users/{operator.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "admin"},
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


@pytest.mark.asyncio
async def test_manual_approval_records_structured_actor(client, db_session, auth_enabled):
    user, project = await _create_user_with_project(
        db_session,
        username="approval_admin",
        role="admin",
        project_key="approval-alpha",
        project_name="Approval Alpha",
        project_role="owner",
    )
    token = await _login(client, "approval_admin")

    created = await client.post(
        "/api/v2/demands",
        headers={"Authorization": f"Bearer {token}"},
        json={"raw_input": "Approve a controlled execution.", "project_id": project.id},
    )
    assert created.status_code == 201
    demand_id = created.json()["data"]["id"]

    approved = await client.post(
        f"/api/v2/demands/{demand_id}/manual-approval",
        headers={"Authorization": f"Bearer {token}"},
        json={"approved": True, "note": "Approved by the current authenticated user."},
    )

    assert approved.status_code == 200
    payload = approved.json()["data"]
    assert payload["manual_approval_status"] == "approved"
    assert payload["manual_approval_user_id"] == user.id
    assert payload["manual_approval_ref"] == "approval_admin"
    assert payload["manual_approval_note"] == "Approved by the current authenticated user."
    assert payload["manual_approval_at"]


@pytest.mark.asyncio
async def test_admin_can_create_and_list_masked_project_secret(
    client,
    db_session,
    auth_enabled,
    monkeypatch,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    _, project = await _create_user_with_project(
        db_session,
        username="secret_admin",
        role="admin",
        project_key="secret-project",
        project_name="Secret Project",
        project_role="owner",
    )
    token = await _login(client, "secret_admin")

    created = await client.post(
        "/api/v2/secrets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "project_id": project.id,
            "name": "dify_api_key",
            "provider": "dify",
            "value": "sk-test-secret-value",
            "description": "Dify workflow key",
        },
    )

    assert created.status_code == 201
    payload = created.json()["data"]
    assert payload["name"] == "dify_api_key"
    assert payload["provider"] == "dify"
    assert payload["value_mask"] == "****alue"
    assert "sk-test-secret-value" not in created.text

    listed = await client.get(
        f"/api/v2/secrets?project_id={project.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"][0]["value_mask"] == "****alue"
    assert "sk-test-secret-value" not in listed.text

    audit = await client.get(
        "/api/v2/audit/events?action=secret.created",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit.status_code == 200
    assert audit.json()["data"][0]["entity_type"] == "secret"


@pytest.mark.asyncio
async def test_secret_store_requires_master_key(client, db_session, auth_enabled, monkeypatch):
    monkeypatch.setattr(settings, "secret_store_master_key", "")
    _, project = await _create_user_with_project(
        db_session,
        username="no_secret_key_admin",
        role="admin",
        project_key="missing-key-project",
        project_name="Missing Key Project",
        project_role="owner",
    )
    token = await _login(client, "no_secret_key_admin")

    response = await client.post(
        "/api/v2/secrets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "project_id": project.id,
            "name": "gitlab_token",
            "provider": "gitlab",
            "value": "token-value",
        },
    )

    assert response.status_code == 400
    assert "SECRET_STORE_MASTER_KEY" in response.json()["message"]


@pytest.mark.asyncio
async def test_project_secret_access_is_project_scoped(
    client,
    db_session,
    auth_enabled,
    monkeypatch,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    _, alpha = await _create_user_with_project(
        db_session,
        username="alpha_secret_admin",
        role="admin",
        project_key="alpha-secret",
        project_name="Alpha Secret",
        project_role="owner",
    )
    _, beta = await _create_user_with_project(
        db_session,
        username="beta_secret_operator",
        project_key="beta-secret",
        project_name="Beta Secret",
    )
    alpha_token = await _login(client, "alpha_secret_admin")
    beta_token = await _login(client, "beta_secret_operator")

    created = await client.post(
        "/api/v2/secrets",
        headers={"Authorization": f"Bearer {alpha_token}"},
        json={
            "project_id": alpha.id,
            "name": "openai_api_key",
            "provider": "openai",
            "value": "openai-secret",
        },
    )
    assert created.status_code == 201
    secret_id = created.json()["data"]["id"]

    beta_list = await client.get(
        f"/api/v2/secrets?project_id={alpha.id}",
        headers={"Authorization": f"Bearer {beta_token}"},
    )
    assert beta_list.status_code == 403

    beta_rotate = await client.post(
        f"/api/v2/secrets/{secret_id}/rotate",
        headers={"Authorization": f"Bearer {beta_token}"},
        json={"value": "new-value"},
    )
    assert beta_rotate.status_code == 403
