"""
Live packet service for real-time mesh packet streaming and spatial resolution.
"""

import logging
import time
from typing import Any

from meshtastic import mesh_pb2

from ..database.connection import get_db_connection
from ..database.repositories import LocationRepository, NodeRepository
from ..utils.node_utils import (
    convert_node_id,
    get_bulk_node_names,
    get_bulk_node_short_names,
)
from ..utils.traceroute_utils import parse_traceroute_payload

logger = logging.getLogger(__name__)

# TTL Cache for known node locations: {node_id: (lat, lon)}
_NODE_LOCATIONS_CACHE: dict[int, tuple[float, float]] = {}
_NODE_LOCATIONS_CACHE_TIME: float = 0.0
_NODE_LOCATIONS_CACHE_TTL: float = 30.0  # 30 seconds


class LivePacketService:
    """Service providing live packet feeds with resolved coordinates and routes."""

    @staticmethod
    def get_known_node_locations() -> dict[int, tuple[float, float]]:
        """
        Fetch latest known node locations, caching for 30s to keep lookups fast.

        Returns:
            Dictionary mapping node_id (int) to (latitude, longitude) floats.
        """
        global _NODE_LOCATIONS_CACHE, _NODE_LOCATIONS_CACHE_TIME
        now = time.time()
        if _NODE_LOCATIONS_CACHE and (now - _NODE_LOCATIONS_CACHE_TIME < _NODE_LOCATIONS_CACHE_TTL):
            return _NODE_LOCATIONS_CACHE

        try:
            locs = LocationRepository.get_node_locations()
            new_cache: dict[int, tuple[float, float]] = {}
            for loc in locs:
                nid = loc.get("node_id")
                lat = loc.get("latitude")
                lon = loc.get("longitude")
                if nid is not None and lat is not None and lon is not None:
                    try:
                        lat_f = float(lat)
                        lon_f = float(lon)
                        if lat_f != 0.0 or lon_f != 0.0:
                            new_cache[int(nid)] = (lat_f, lon_f)
                    except (ValueError, TypeError):
                        continue

            _NODE_LOCATIONS_CACHE = new_cache
            _NODE_LOCATIONS_CACHE_TIME = now
            return _NODE_LOCATIONS_CACHE
        except Exception as e:
            logger.error(f"Error refreshing node locations cache in LivePacketService: {e}")
            return _NODE_LOCATIONS_CACHE

    @classmethod
    def get_live_packets(
        cls,
        after_id: int | None = None,
        limit: int = 50,
        include_unlocated: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch recent or incremental packets with resolved geospatial routes.

        Args:
            after_id: If specified and > 0, return packets with id > after_id.
                      If 0 or None, returns the most recent `limit` packets.
            limit: Maximum packets to retrieve (clamped to 1..100).
            include_unlocated: If True, include packets where sender/gateway lack coordinates.

        Returns:
            Dictionary with:
              - 'packets': List of grouped packet objects ready for map animation & feed.
              - 'latest_id': Highest packet id in database for cursor polling.
              - 'count': Number of packets returned.
        """
        limit = max(1, min(100, int(limit)))
        loc_cache = cls.get_known_node_locations()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if after_id is not None and after_id > 0:
                query = """
                    SELECT
                        id, timestamp, mesh_packet_id, from_node_id, to_node_id,
                        portnum, portnum_name, gateway_id, channel_id, rssi, snr,
                        hop_start, hop_limit, relay_node, rx_time, raw_payload
                    FROM packet_history
                    WHERE id > ?
                    ORDER BY id ASC
                    LIMIT ?
                """
                cursor.execute(query, (after_id, limit))
                rows = cursor.fetchall()
            else:
                # Initial load: grab latest N rows and order chronologically ascending
                query = """
                    SELECT
                        id, timestamp, mesh_packet_id, from_node_id, to_node_id,
                        portnum, portnum_name, gateway_id, channel_id, rssi, snr,
                        hop_start, hop_limit, relay_node, rx_time, raw_payload
                    FROM packet_history
                    ORDER BY id DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                rows = list(reversed(cursor.fetchall()))

            # Check highest id and max timestamp in table even if rows is empty
            cursor.execute("SELECT MAX(id), MAX(timestamp) FROM packet_history")
            max_row = cursor.fetchone()
            global_latest_id = max_row[0] if max_row and max_row[0] is not None else 0
            global_latest_timestamp = float(max_row[1]) if max_row and max_row[1] is not None else 0.0

        finally:
            conn.close()

        if not rows:
            return {
                "packets": [],
                "latest_id": global_latest_id,
                "latest_timestamp": global_latest_timestamp,
                "count": 0,
            }

        output_packets = cls._process_packet_rows(rows, loc_cache, include_unlocated)
        latest_batch_id = max(r["id"] for r in rows)
        effective_latest_id = max(global_latest_id, latest_batch_id)

        return {
            "packets": output_packets,
            "latest_id": effective_latest_id,
            "latest_timestamp": global_latest_timestamp,
            "count": len(output_packets),
        }

    @classmethod
    def get_historical_packets(
        cls,
        start_time: float,
        end_time: float,
        limit: int = 500,
        include_unlocated: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch historical packets within [start_time, end_time] ordered chronologically.

        Args:
            start_time: Start unix timestamp (seconds).
            end_time: End unix timestamp (seconds).
            limit: Maximum packets to retrieve (clamped to 1..2000).
            include_unlocated: If True, include packets where sender/gateway lack coordinates.

        Returns:
            Dictionary with:
              - 'packets': List of grouped packet objects ready for map animation & feed.
              - 'start_time': Query start timestamp.
              - 'end_time': Query end timestamp.
              - 'count': Number of packets returned.
        """
        limit = max(1, min(2000, int(limit)))
        loc_cache = cls.get_known_node_locations()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            query = """
                SELECT
                    id, timestamp, mesh_packet_id, from_node_id, to_node_id,
                    portnum, portnum_name, gateway_id, channel_id, rssi, snr,
                    hop_start, hop_limit, relay_node, rx_time, raw_payload
                FROM packet_history
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC, id ASC
                LIMIT ?
            """
            cursor.execute(query, (start_time, end_time, limit))
            rows = cursor.fetchall()
        finally:
            conn.close()

        if not rows:
            return {
                "packets": [],
                "start_time": start_time,
                "end_time": end_time,
                "count": 0,
            }

        output_packets = cls._process_packet_rows(rows, loc_cache, include_unlocated)

        return {
            "packets": output_packets,
            "start_time": start_time,
            "end_time": end_time,
            "count": len(output_packets),
        }

    @classmethod
    def _process_packet_rows(
        cls,
        rows: list[Any],
        loc_cache: dict[int, tuple[float, float]],
        include_unlocated: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Transform raw database packet rows into structured packet objects with
        resolved geospatial reception paths, relay candidate inferences, and traceroutes.
        """
        if not rows:
            return []

        # -------------------------------------------------------------
        # 1. Update location cache dynamically if any position packets exist in batch
        # -------------------------------------------------------------
        for r in rows:
            if r["portnum"] == 3 and r["raw_payload"] and r["from_node_id"]:
                try:
                    pos = mesh_pb2.Position()
                    pos.ParseFromString(r["raw_payload"])
                    if pos.latitude_i and pos.longitude_i:
                        lat_f = pos.latitude_i / 1e7
                        lon_f = pos.longitude_i / 1e7
                        if (abs(lat_f) > 0.05 or abs(lon_f) > 0.05) and -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0:
                            f_id = convert_node_id(r["from_node_id"])
                            if f_id:
                                loc_cache[f_id] = (lat_f, lon_f)
                except Exception:
                    pass

        # -------------------------------------------------------------
        # 2. Gather all node IDs for bulk name lookups
        # -------------------------------------------------------------
        node_ids_to_resolve: set[int] = set()
        relay_pairs: list[tuple[int, int]] = []

        for r in rows:
            if r["from_node_id"]:
                f_id = convert_node_id(r["from_node_id"])
                if f_id:
                    node_ids_to_resolve.add(f_id)
            if r["to_node_id"]:
                t_id = convert_node_id(r["to_node_id"])
                if t_id and t_id != 0xFFFFFFFF:
                    node_ids_to_resolve.add(t_id)
            if r["gateway_id"]:
                gw_int = convert_node_id(r["gateway_id"])
                if gw_int:
                    node_ids_to_resolve.add(gw_int)
                    # Check for 1-hop relay candidate lookup
                    hop_start = r["hop_start"] or 0
                    hop_limit = r["hop_limit"] or 0
                    hops_away = hop_start - hop_limit
                    if hops_away >= 1 and r["relay_node"] and r["relay_node"] != 0:
                        relay_pairs.append((gw_int, r["relay_node"] & 0xFF))

        # Look up bulk names
        node_names = get_bulk_node_names(list(node_ids_to_resolve))
        node_short_names = get_bulk_node_short_names(list(node_ids_to_resolve))

        # Look up relay candidates
        candidates_by_pair: dict[int, dict[int, list[dict[str, Any]]]] = {}
        if relay_pairs:
            try:
                candidates_by_pair = NodeRepository.get_relay_node_candidates_for_pairs(relay_pairs)
            except Exception as e:
                logger.warning(f"Error looking up relay candidates for live packets: {e}")

        # -------------------------------------------------------------
        # 3. Group receptions by mesh_packet_id for multi-gateway fan-out
        #    Only merge into the same transmission within a 30s broadcast window.
        # -------------------------------------------------------------
        groups: list[list[Any]] = []
        active_groups: dict[tuple[int, Any], list[Any]] = {}

        for r in rows:
            mp_id = r["mesh_packet_id"]
            from_id = r["from_node_id"]
            if mp_id is not None and mp_id != 0:
                key = (mp_id, from_id)
                if key in active_groups and abs(r["timestamp"] - active_groups[key][0]["timestamp"]) <= 30.0:
                    active_groups[key].append(r)
                    continue
                new_group = [r]
                active_groups[key] = new_group
                groups.append(new_group)
            else:
                groups.append([r])

        output_packets: list[dict[str, Any]] = []

        for group_rows in groups:
            prim = group_rows[0]
            from_id = convert_node_id(prim["from_node_id"]) if prim["from_node_id"] is not None else None
            to_id = convert_node_id(prim["to_node_id"]) if prim["to_node_id"] is not None else None
            is_broadcast = (to_id is None or to_id == 0xFFFFFFFF)

            from_loc = loc_cache.get(from_id) if from_id is not None else None

            # Decode text preview if plain chat message
            text_preview: str | None = None
            if prim["portnum"] == 1 or prim["portnum_name"] == "TEXT_MESSAGE_APP":
                if prim["raw_payload"]:
                    try:
                        text_preview = prim["raw_payload"].decode("utf-8", errors="replace")
                    except Exception:
                        text_preview = None

            # Build list of gateway receptions
            receptions: list[dict[str, Any]] = []
            has_positioned_reception = False

            for r in group_rows:
                gw_str = r["gateway_id"] or ""
                gw_int = convert_node_id(gw_str) if gw_str else None
                gw_loc = loc_cache.get(gw_int) if gw_int is not None else None
                if gw_loc is not None:
                    has_positioned_reception = True

                hop_start = r["hop_start"] or 0
                hop_limit = r["hop_limit"] or 0
                hops_away = max(0, hop_start - hop_limit)

                # Gateway hearing itself transmits directly (0 hops away)
                if from_id is not None and gw_int is not None and from_id == gw_int:
                    hops_away = 0

                # Determine Path Type & Coordinates (Honest pathing - no invented routes)
                path_type = "unlocated"
                path_coords: list[list[float]] = []
                relay_info: dict[str, Any] | None = None
                traceroute_hops: list[dict[str, Any]] = []

                # 1. Traceroute (ROUTING_APP or TRACEROUTE_APP with discovered route)
                is_trace_port = (r["portnum"] in (5, 70) or r["portnum_name"] in ("TRACEROUTE_APP", "ROUTING_APP"))
                if is_trace_port and r["raw_payload"]:
                    try:
                        r_data = parse_traceroute_payload(r["raw_payload"])
                        hop_ids = r_data.get("route_nodes", []) or r_data.get("route_back", [])
                        if hop_ids:
                            path_type = "traceroute"
                            if from_loc:
                                path_coords.append([from_loc[0], from_loc[1]])
                            for hop_id in hop_ids:
                                hop_loc = loc_cache.get(hop_id)
                                hop_name = node_names.get(hop_id, f"!{hop_id:08x}")
                                traceroute_hops.append({
                                    "node_id": hop_id,
                                    "hex_id": f"!{hop_id:08x}",
                                    "name": hop_name,
                                    "latitude": hop_loc[0] if hop_loc else None,
                                    "longitude": hop_loc[1] if hop_loc else None,
                                })
                                if hop_loc:
                                    path_coords.append([hop_loc[0], hop_loc[1]])
                            if gw_loc:
                                path_coords.append([gw_loc[0], gw_loc[1]])
                    except Exception:
                        pass

                if path_type == "traceroute":
                    pass
                elif from_loc is not None and gw_loc is not None:
                    # 2. Direct RF reception (0 hops) or gateway transmitting its own packet
                    if hops_away == 0:
                        path_type = "direct"
                        path_coords = [
                            [from_loc[0], from_loc[1]],
                            [gw_loc[0], gw_loc[1]],
                        ]

                    # 3. 1-hop with identified relay candidate
                    elif hops_away == 1 and r["relay_node"] and r["relay_node"] != 0 and gw_int is not None:
                        relay_last_byte = r["relay_node"] & 0xFF
                        gw_candidates = candidates_by_pair.get(gw_int, {}).get(relay_last_byte, [])
                        if len(gw_candidates) == 1:
                            cand = gw_candidates[0]
                            cand_id = cand.get("node_id")
                            cand_loc = loc_cache.get(cand_id) if cand_id is not None else None
                            relay_info = {
                                "node_id": cand_id,
                                "hex_id": cand.get("hex_id", f"!{cand_id:08x}"),
                                "name": cand.get("long_name") or cand.get("short_name") or f"!{cand_id:08x}",
                                "location": {"latitude": cand_loc[0], "longitude": cand_loc[1]} if cand_loc else None,
                            }
                            if cand_loc is not None:
                                path_type = "relay"
                                path_coords = [
                                    [from_loc[0], from_loc[1]],
                                    [cand_loc[0], cand_loc[1]],
                                    [gw_loc[0], gw_loc[1]],
                                ]
                            else:
                                path_type = "arc_unknown"
                                path_coords = [
                                    [from_loc[0], from_loc[1]],
                                    [gw_loc[0], gw_loc[1]],
                                ]
                        else:
                            path_type = "arc_unknown"
                            path_coords = [[from_loc[0], from_loc[1]], [gw_loc[0], gw_loc[1]]]

                    # 4. Multi-hop (hops_away >= 2) with identified last relay candidate
                    elif hops_away >= 2 and r["relay_node"] and r["relay_node"] != 0 and gw_int is not None:
                        relay_last_byte = r["relay_node"] & 0xFF
                        gw_candidates = candidates_by_pair.get(gw_int, {}).get(relay_last_byte, [])
                        if len(gw_candidates) == 1:
                            cand = gw_candidates[0]
                            cand_id = cand.get("node_id")
                            cand_loc = loc_cache.get(cand_id) if cand_id is not None else None
                            relay_info = {
                                "node_id": cand_id,
                                "hex_id": cand.get("hex_id", f"!{cand_id:08x}"),
                                "name": cand.get("long_name") or cand.get("short_name") or f"!{cand_id:08x}",
                                "location": {"latitude": cand_loc[0], "longitude": cand_loc[1]} if cand_loc else None,
                                "remaining_hops": hops_away - 1,
                            }
                            if cand_loc is not None:
                                path_type = "multi_hop_relay"
                                path_coords = [
                                    [from_loc[0], from_loc[1]],
                                    [cand_loc[0], cand_loc[1]],
                                    [gw_loc[0], gw_loc[1]],
                                ]
                            else:
                                path_type = "arc_unknown"
                                path_coords = [
                                    [from_loc[0], from_loc[1]],
                                    [gw_loc[0], gw_loc[1]],
                                ]
                        else:
                            path_type = "arc_unknown"
                            path_coords = [[from_loc[0], from_loc[1]], [gw_loc[0], gw_loc[1]]]

                    # 5. Multi-hop unknown intermediate (>= 2 hops or unresolved relay)
                    else:
                        path_type = "arc_unknown"
                        path_coords = [
                            [from_loc[0], from_loc[1]],
                            [gw_loc[0], gw_loc[1]],
                        ]
                else:
                    path_type = "unlocated"

                receptions.append({
                    "packet_id": r["id"],
                    "gateway_id": gw_str,
                    "gateway_node_id": gw_int,
                    "gateway_name": node_names.get(gw_int, gw_str) if gw_int else gw_str,
                    "gateway_location": {"latitude": gw_loc[0], "longitude": gw_loc[1]} if gw_loc else None,
                    "rssi": r["rssi"],
                    "snr": r["snr"],
                    "rx_time": r["rx_time"],
                    "hop_start": hop_start,
                    "hop_limit": hop_limit,
                    "hops_away": hops_away,
                    "relay_node": r["relay_node"],
                    "relay_candidate": relay_info,
                    "path_type": path_type,
                    "path_coords": path_coords,
                    "traceroute_hops": traceroute_hops,
                })

            is_positioned = (from_loc is not None and has_positioned_reception)
            if not include_unlocated and not is_positioned:
                continue

            # Consolidated packet object
            output_packets.append({
                "id": prim["id"],
                "latest_packet_id": max(r["id"] for r in group_rows),
                "mesh_packet_id": prim["mesh_packet_id"],
                "timestamp": prim["timestamp"],
                "portnum": prim["portnum"],
                "portnum_name": prim["portnum_name"] or "UNKNOWN_APP",
                "channel_id": prim["channel_id"] or "",
                "from_node_id": from_id,
                "from_node_hex": f"!{from_id:08x}" if from_id else None,
                "from_node_name": node_names.get(from_id, f"!{from_id:08x}" if from_id else "Unknown"),
                "from_node_short_name": node_short_names.get(from_id),
                "from_location": {"latitude": from_loc[0], "longitude": from_loc[1]} if from_loc else None,
                "to_node_id": to_id,
                "to_node_hex": "^all" if is_broadcast else (f"!{to_id:08x}" if to_id else None),
                "to_node_name": "Broadcast" if is_broadcast else node_names.get(to_id, f"!{to_id:08x}" if to_id else "Unknown"),
                "is_broadcast": is_broadcast,
                "is_positioned": is_positioned,
                "receptions": receptions,
                "gateway_count": len(receptions),
                "text_preview": text_preview,
            })
        return output_packets

