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
        assert "latest_timestamp" in data
        assert "count" in data
        assert isinstance(data["packets"], list)
        assert isinstance(data["latest_id"], int)
        assert isinstance(data["latest_timestamp"], (int, float))
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


class TestLivePacketProcessingLogic:
    """Test LivePacketService._process_packet_rows algorithmic logic."""

    @pytest.mark.integration
    def test_grouping_window_merges_receptions_within_30s(self):
        """Test that packets with identical mesh_packet_id within 30s are merged into one broadcast."""
        from malla.services.live_packet_service import LivePacketService

        loc_cache = {100: (37.77, -122.41), 200: (37.78, -122.42), 300: (37.79, -122.43)}
        rows = [
            {
                "id": 1,
                "timestamp": 1000.0,
                "mesh_packet_id": 9999,
                "from_node_id": 100,
                "to_node_id": 0xFFFFFFFF,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!000000c8",  # 200
                "channel_id": "LongFast",
                "rssi": -80,
                "snr": 8.0,
                "hop_start": 3,
                "hop_limit": 3,
                "relay_node": 0,
                "rx_time": 1000,
                "raw_payload": b"Hello",
            },
            {
                "id": 2,
                "timestamp": 1002.5,
                "mesh_packet_id": 9999,
                "from_node_id": 100,
                "to_node_id": 0xFFFFFFFF,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!0000012c",  # 300
                "channel_id": "LongFast",
                "rssi": -85,
                "snr": 6.5,
                "hop_start": 3,
                "hop_limit": 3,
                "relay_node": 0,
                "rx_time": 1002,
                "raw_payload": b"Hello",
            },
        ]

        result = LivePacketService._process_packet_rows(rows, loc_cache)
        assert len(result) == 1
        assert result[0]["mesh_packet_id"] == 9999
        assert result[0]["gateway_count"] == 2
        assert len(result[0]["receptions"]) == 2

    @pytest.mark.integration
    def test_grouping_window_separates_receptions_over_30s(self):
        """Test that packets with recurring mesh_packet_id hours apart are not merged."""
        from malla.services.live_packet_service import LivePacketService

        loc_cache = {100: (37.77, -122.41), 200: (37.78, -122.42)}
        rows = [
            {
                "id": 1,
                "timestamp": 1000.0,
                "mesh_packet_id": 9999,
                "from_node_id": 100,
                "to_node_id": 0xFFFFFFFF,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!000000c8",
                "channel_id": "LongFast",
                "rssi": -80,
                "snr": 8.0,
                "hop_start": 3,
                "hop_limit": 3,
                "relay_node": 0,
                "rx_time": 1000,
                "raw_payload": b"Hello",
            },
            {
                "id": 100,
                "timestamp": 9050.0,  # ~2.2 hours later
                "mesh_packet_id": 9999,
                "from_node_id": 100,
                "to_node_id": 0xFFFFFFFF,
                "portnum": 1,
                "portnum_name": "TEXT_MESSAGE_APP",
                "gateway_id": "!000000c8",
                "channel_id": "LongFast",
                "rssi": -82,
                "snr": 7.0,
                "hop_start": 3,
                "hop_limit": 3,
                "relay_node": 0,
                "rx_time": 9050,
                "raw_payload": b"Later",
            },
        ]

        result = LivePacketService._process_packet_rows(rows, loc_cache)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 100

    @pytest.mark.integration
    def test_self_packet_path_type_and_hops(self):
        """Test that packets transmitted by gateway itself resolve as 0-hop direct paths."""
        from malla.services.live_packet_service import LivePacketService

        gw_id = 500
        loc_cache = {gw_id: (37.77, -122.41)}
        rows = [
            {
                "id": 10,
                "timestamp": 2000.0,
                "mesh_packet_id": 1234,
                "from_node_id": gw_id,
                "to_node_id": 0xFFFFFFFF,
                "portnum": 67,
                "portnum_name": "TELEMETRY_APP",
                "gateway_id": f"!{gw_id:08x}",
                "channel_id": "LongFast",
                "rssi": 0,
                "snr": 10.0,
                "hop_start": 3,
                "hop_limit": 0,  # Would look like 3 hops away if not self-checked
                "relay_node": 0,
                "rx_time": 2000,
                "raw_payload": None,
            }
        ]

        result = LivePacketService._process_packet_rows(rows, loc_cache)
        assert len(result) == 1
        rec = result[0]["receptions"][0]
        assert rec["hops_away"] == 0
        assert rec["path_type"] == "direct"
        assert rec["path_coords"] == [[37.77, -122.41], [37.77, -122.41]]


