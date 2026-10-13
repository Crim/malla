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
        assert b"packetInspectorCard" in response.data
        assert b"feedFilterPills" in response.data
        assert b"vcrSlider" in response.data
        assert b"jumpToLiveBtn" in response.data
        assert b"vcrRangeGroup" in response.data

    @pytest.mark.integration
    def test_live_map_in_navbar(self, client):
        """Test that the Live Map nav link is present in base layout."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"/live-map" in response.data
        assert b"Live Map" in response.data


class TestLivePacketsAPI:
    """Test /api/live/packets endpoint functionality."""

    @pytest.mark.integration
    def test_live_packets_endpoint_structure(self, client):
        """Test that /api/live/packets returns valid JSON structure."""
        response = client.get("/api/live/packets")
        assert response.status_code == 200
        data = response.get_json()
        assert "packets" in data
        assert "latest_id" in data
        assert "count" in data
        assert isinstance(data["packets"], list)
        assert isinstance(data["latest_id"], int)
        assert data["count"] == len(data["packets"])

    @pytest.mark.integration
    def test_live_packets_fields(self, client):
        """Test that packet items contain required metadata and geospatial fields."""
        response = client.get("/api/live/packets?limit=10")
        assert response.status_code == 200
        data = response.get_json()

        if data["count"] > 0:
            pkt = data["packets"][0]
            assert "id" in pkt
            assert "timestamp" in pkt
            assert "portnum" in pkt
            assert "portnum_name" in pkt
            assert "from_node_id" in pkt
            assert "from_node_hex" in pkt
            assert "from_node_name" in pkt
            assert "is_broadcast" in pkt
            assert "is_positioned" in pkt
            assert "receptions" in pkt
            assert isinstance(pkt["receptions"], list)

            if len(pkt["receptions"]) > 0:
                rec = pkt["receptions"][0]
                assert "gateway_id" in rec
                assert "hops_away" in rec
                assert "path_type" in rec
                assert "path_coords" in rec
                assert rec["path_type"] in ("direct", "relay", "multi_hop_relay", "traceroute", "arc_unknown", "unlocated")

    @pytest.mark.integration
    def test_live_packets_pagination_after_id(self, client):
        """Test that after_id only returns newer packets."""
        # First get small batch
        response = client.get("/api/live/packets?limit=5")
        data = response.get_json()
        if data["count"] > 1:
            first_pkt_id = data["packets"][0]["id"]
            # Request packets strictly after first_pkt_id
            response_after = client.get(f"/api/live/packets?after_id={first_pkt_id}&limit=10")
            assert response_after.status_code == 200
            data_after = response_after.get_json()
            for pkt in data_after["packets"]:
                assert pkt["id"] > first_pkt_id

    @pytest.mark.integration
    def test_live_packets_limit_clamping(self, client):
        """Test that limit is properly bounded."""
        response = client.get("/api/live/packets?limit=500")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] <= 100

    @pytest.mark.integration
    def test_live_packets_returns_204_when_no_new_packets(self, client):
        """Test that after_id returns HTTP 204 No Content when no newer packets exist."""
        # Use an impossibly high packet ID
        response = client.get("/api/live/packets?after_id=999999999")
        assert response.status_code == 204
        assert response.data == b""
        assert "no-cache" in response.headers.get("Cache-Control", "")


class TestLiveHistoryAPI:
    """Test /api/live/history endpoint functionality."""

    @pytest.mark.integration
    def test_live_history_missing_params(self, client):
        """Test that missing start_time or end_time returns HTTP 400."""
        response = client.get("/api/live/history")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

        response_partial = client.get("/api/live/history?start_time=1000")
        assert response_partial.status_code == 400

    @pytest.mark.integration
    def test_live_history_invalid_timestamps(self, client):
        """Test that non-numeric timestamps return HTTP 400."""
        response = client.get("/api/live/history?start_time=abc&end_time=xyz")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    @pytest.mark.integration
    def test_live_history_inverted_range(self, client):
        """Test that start_time > end_time returns HTTP 400."""
        response = client.get("/api/live/history?start_time=5000&end_time=1000")
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    @pytest.mark.integration
    def test_live_history_valid_query_structure(self, client):
        """Test that /api/live/history returns expected response structure."""
        response = client.get("/api/live/history?start_time=0&end_time=2500000000&limit=50")
        assert response.status_code == 200
        data = response.get_json()
        assert "packets" in data
        assert "start_time" in data
        assert "end_time" in data
        assert "count" in data
        assert isinstance(data["packets"], list)
        assert data["count"] == len(data["packets"])

    @pytest.mark.integration
    def test_live_history_limit_clamping(self, client):
        """Test that limit parameter is parsed and bounded without error."""
        response = client.get("/api/live/history?start_time=0&end_time=2500000000&limit=5000")
        assert response.status_code == 200
        data = response.get_json()
        assert data["count"] <= 2000

    @pytest.mark.integration
    def test_live_history_fields(self, client):
        """Test that historical packets contain required route and geometry fields."""
        response = client.get("/api/live/history?start_time=0&end_time=2500000000&limit=10")
        assert response.status_code == 200
        data = response.get_json()
        if data["count"] > 0:
            pkt = data["packets"][0]
            assert "id" in pkt
            assert "timestamp" in pkt
            assert "from_node_id" in pkt
            assert "receptions" in pkt
            assert isinstance(pkt["receptions"], list)
            if len(pkt["receptions"]) > 0:
                rec = pkt["receptions"][0]
                assert "gateway_id" in rec
                assert "path_type" in rec
                assert "path_coords" in rec


