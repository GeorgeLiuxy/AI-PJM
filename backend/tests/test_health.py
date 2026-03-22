"""Health check endpoint tests"""

import pytest
from app.common.responses import HealthResponse


@pytest.mark.asyncio
async def test_health_check(async_client):
    """Test health check endpoint returns 200"""
    response = await async_client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data
