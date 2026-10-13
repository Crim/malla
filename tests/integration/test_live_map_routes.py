"""Integration tests for the Live Map feature routes and pages."""

import pytest


class TestLiveMapRoutes:
    """Test /live-map page and associated routes."""

    @pytest.mark.integration
    def test_live_map_route_loads_successfully(self, client):
        """Test that the live map page loads with HTTP 200."""
        response = client.get("/live-map")
        assert response.status_code == 200
        assert b"Live Map" in response.data
        assert b"liveMap" in response.data
        assert b"liveFeedSidebar" in response.data
        assert b"live-status-pill" in response.data

    @pytest.mark.integration
    def test_live_map_in_navbar(self, client):
        """Test that the Live Map nav link is present in base layout."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"/live-map" in response.data
        assert b"Live Map" in response.data
