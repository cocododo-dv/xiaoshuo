from __future__ import annotations

from fastapi.testclient import TestClient


def test_one_off_reference_demo_route_is_not_registered(client: TestClient) -> None:
    removed_slug = "dragon-" + "xianxia"
    removed_base = "/api/v1/" + "demo"

    response = client.get(f"{removed_base}/{removed_slug}/status")

    assert response.status_code == 404
