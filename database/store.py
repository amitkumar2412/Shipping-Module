"""Store — all read/write operations on the PostgreSQL database."""
import json

import psycopg2.extras

from .connection import connect, now_utc, ts_to_utc, ts_to_local, b
from .schema import TABLES, MSD_COLS, MSD_INSERT


class Store:
    def __init__(self):
        self.conn = connect()
        self._apply_schema()

    def _apply_schema(self):
        with self.conn.cursor() as cur:
            for stmt in TABLES:
                cur.execute(stmt)
        self.conn.commit()

    def _cur(self):
        return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ---- watch list --------------------------------------------------------

    def add_ship(self, ship_id, label=None):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ships (ship_id, label, active, added_at) VALUES (%s, %s, 1, %s) "
                "ON CONFLICT (ship_id) DO UPDATE SET active = 1, label = COALESCE(EXCLUDED.label, ships.label)",
                (ship_id, label, now_utc()),
            )
        self.conn.commit()

    def remove_ship(self, ship_id):
        with self.conn.cursor() as cur:
            cur.execute("UPDATE ships SET active = 0 WHERE ship_id = %s", (ship_id,))
        self.conn.commit()

    def active_ships(self):
        with self._cur() as cur:
            cur.execute("SELECT ship_id FROM ships WHERE active = 1 ORDER BY ship_id")
            return [r["ship_id"] for r in cur.fetchall()]

    def list_all_ships(self):
        with self._cur() as cur:
            cur.execute(
                "SELECT s.ship_id, s.active, v.name, v.imo, v.updated_at "
                "FROM ships s LEFT JOIN vessels v USING (ship_id) ORDER BY s.ship_id"
            )
            return [dict(r) for r in cur.fetchall()]

    # ---- saving a scrape ---------------------------------------------------

    def save(self, ship_id, data):
        """Saves one scrape result. Returns True if a new AIS position was stored."""
        t = now_utc()
        g = data["general"]
        s = data["summary"] or {}
        p = data["position"] or {}
        v = data["voyage"] or {}
        ports = data["ports"]
        ct = g.get("commercial_type") or {}
        new_position = False

        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO vessels (
                    ship_id, name, ais_name, imo, eni, mmsi, length, width, callsign,
                    country, country_code, type, type_id, com_fleet_grouped_type_id,
                    com_fleet_grouped_type_name, type_color_id, subtype, year_built,
                    service_status, home_port, ais_transponder_class, is_navigational_aid,
                    corresponding_roaming_station_id, market_id, market_name, size_class_name,
                    ais_ship_type, summary_position, summary_particulars, first_seen_at, updated_at
                ) VALUES (
                    %(ship_id)s, %(name)s, %(ais_name)s, %(imo)s, %(eni)s, %(mmsi)s, %(length)s,
                    %(width)s, %(callsign)s, %(country)s, %(country_code)s, %(type)s, %(type_id)s,
                    %(cfg_id)s, %(cfg_name)s, %(type_color_id)s, %(subtype)s, %(year_built)s,
                    %(service_status)s, %(home_port)s, %(ais_class)s, %(is_nav_aid)s, %(roaming)s,
                    %(market_id)s, %(market_name)s, %(size_class)s, %(ais_ship_type)s, %(sum_pos)s,
                    %(sum_part)s, %(t)s, %(t)s
                )
                ON CONFLICT (ship_id) DO UPDATE SET
                    name=EXCLUDED.name, ais_name=EXCLUDED.ais_name, imo=EXCLUDED.imo,
                    eni=EXCLUDED.eni, mmsi=EXCLUDED.mmsi, length=EXCLUDED.length,
                    width=EXCLUDED.width, callsign=EXCLUDED.callsign, country=EXCLUDED.country,
                    country_code=EXCLUDED.country_code, type=EXCLUDED.type, type_id=EXCLUDED.type_id,
                    com_fleet_grouped_type_id=EXCLUDED.com_fleet_grouped_type_id,
                    com_fleet_grouped_type_name=EXCLUDED.com_fleet_grouped_type_name,
                    type_color_id=EXCLUDED.type_color_id, subtype=EXCLUDED.subtype,
                    year_built=EXCLUDED.year_built, service_status=EXCLUDED.service_status,
                    home_port=EXCLUDED.home_port, ais_transponder_class=EXCLUDED.ais_transponder_class,
                    is_navigational_aid=EXCLUDED.is_navigational_aid,
                    corresponding_roaming_station_id=EXCLUDED.corresponding_roaming_station_id,
                    market_id=EXCLUDED.market_id, market_name=EXCLUDED.market_name,
                    size_class_name=EXCLUDED.size_class_name, ais_ship_type=EXCLUDED.ais_ship_type,
                    summary_position=EXCLUDED.summary_position,
                    summary_particulars=EXCLUDED.summary_particulars, updated_at=EXCLUDED.updated_at""",
                dict(
                    ship_id=ship_id, name=g.get("name"), ais_name=g.get("aisName"),
                    imo=g.get("imo"), eni=g.get("eni"), mmsi=g.get("mmsi"),
                    length=g.get("length"), width=g.get("width"), callsign=g.get("callsign"),
                    country=g.get("country"), country_code=g.get("countryCode"),
                    type=g.get("type"), type_id=g.get("typeId"),
                    cfg_id=g.get("comFleetGroupedTypeId"), cfg_name=g.get("comFleetGroupedTypeName"),
                    type_color_id=g.get("typeColorId"), subtype=g.get("subtype"),
                    year_built=g.get("yearBuilt"), service_status=g.get("serviceStatus"),
                    home_port=g.get("homePort"), ais_class=g.get("aisTransponderClass"),
                    is_nav_aid=b(g.get("isNavigationalAid")),
                    roaming=g.get("correspondingRoamingStationId"),
                    market_id=ct.get("market_id"), market_name=ct.get("market_name"),
                    size_class=ct.get("size_class_name"), ais_ship_type=g.get("aisShipType"),
                    sum_pos=s.get("position"), sum_part=s.get("particulars"), t=t,
                ),
            )

            for pid, port in ports.items():
                if port:
                    country = port.get("country") or {}
                    cur.execute(
                        """INSERT INTO shippingport (port_id, name, unlocode, country, country_code, lat, lon, timezone, raw_json, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (port_id) DO UPDATE SET
                            name=EXCLUDED.name, unlocode=EXCLUDED.unlocode, country=EXCLUDED.country,
                            country_code=EXCLUDED.country_code, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
                            timezone=EXCLUDED.timezone, raw_json=EXCLUDED.raw_json, updated_at=EXCLUDED.updated_at""",
                        (pid, port.get("name"), port.get("unlocode"), country.get("name"),
                         country.get("code"), port.get("lat"), port.get("lon"),
                         port.get("timezone"), json.dumps(port), t),
                    )

            if p.get("timestamp") is not None:
                cur.execute(
                    """INSERT INTO positions (
                        ship_id, position_ts, position_utc, vessel_local_time, timezone, lat, lon,
                        speed, course, heading, rate_of_turn, draught, navigational_status,
                        station_id, station_type, station_name, operator_name, area_name,
                        area_code, is_vessel_in_range, has_newer_satellite_position, scraped_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ship_id, position_ts) DO NOTHING""",
                    (ship_id, p["timestamp"], ts_to_utc(p["timestamp"]),
                     ts_to_local(p["timestamp"], p.get("timezone")), p.get("timezone"),
                     p.get("lat"), p.get("lon"), p.get("speed"), p.get("course"),
                     p.get("heading"), p.get("rateOfTurn"), p.get("draught"),
                     p.get("navigationalStatus"), p.get("stationId"), p.get("stationType"),
                     p.get("stationName"), p.get("operatorName"), p.get("areaName"),
                     p.get("areaCode"), b(p.get("isVesselInRange")),
                     b(p.get("hasNewerSatellitePosition")), t),
                )
                new_position = cur.rowcount > 0

            if v:
                dep = ports.get(v.get("departurePortId")) or {}
                arr = ports.get(v.get("arrivalPortId")) or {}
                cur.execute(
                    """INSERT INTO voyages (
                        ship_id, departure_port_id, departure_port_name, departure_unlocode,
                        departure_ts, departure_utc, departure_label, arrival_port_id,
                        arrival_port_name, arrival_unlocode, arrival_ts, arrival_utc,
                        arrival_label, reported_destination, eta_ts, eta_utc, eta_timezone,
                        eta_calc_ts, eta_calc_timezone, progress, distance_travelled,
                        distance_to_go, last_port_time, load_condition, estimated_route_found,
                        previous_departure_port_id, previous_arrival_ts, first_seen_at, last_seen_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ship_id, departure_port_id, departure_ts, reported_destination, eta_ts) DO UPDATE SET
                        progress=EXCLUDED.progress, distance_travelled=EXCLUDED.distance_travelled,
                        distance_to_go=EXCLUDED.distance_to_go, eta_calc_ts=EXCLUDED.eta_calc_ts,
                        arrival_ts=EXCLUDED.arrival_ts, arrival_utc=EXCLUDED.arrival_utc,
                        arrival_label=EXCLUDED.arrival_label, load_condition=EXCLUDED.load_condition,
                        last_seen_at=EXCLUDED.last_seen_at""",
                    (ship_id, v.get("departurePortId"), dep.get("name"), dep.get("unlocode"),
                     v.get("departureTimestamp"), ts_to_utc(v.get("departureTimestamp")),
                     v.get("departureLabel"), v.get("arrivalPortId"), arr.get("name"),
                     arr.get("unlocode"), v.get("arrivalTimestamp"),
                     ts_to_utc(v.get("arrivalTimestamp")), v.get("arrivalLabel"),
                     v.get("reportedDestination"), v.get("eta"), ts_to_utc(v.get("eta")),
                     v.get("etaTimezone"), v.get("etaCalc"), v.get("etaCalcTimezone"),
                     v.get("progress"), v.get("distanceTravelled"), v.get("distanceToGo"),
                     v.get("lastPortTime"), v.get("loadCondition"),
                     b(v.get("estimatedRouteFound")), v.get("previousDeparturePortId"),
                     v.get("previousArrivalTimestamp"), t, t),
                )

            cur.execute(
                "INSERT INTO snapshots (ship_id, scraped_at, raw_json) VALUES (%s, %s, %s)",
                (ship_id, t, json.dumps(data, default=str)),
            )
            cur.execute(
                "INSERT INTO scrape_log (ship_id, scraped_at, ok, new_position) VALUES (%s, %s, 1, %s)",
                (ship_id, t, int(new_position)),
            )

        self.conn.commit()
        return new_position

    def log_error(self, ship_id, error):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO scrape_log (ship_id, scraped_at, ok, error) VALUES (%s, %s, 0, %s)",
                (ship_id, now_utc(), str(error)),
            )
        self.conn.commit()

    # ---- reading -----------------------------------------------------------

    def latest(self, ship_id):
        """Returns the combined current record for one ship: vessel + position + voyage."""
        with self._cur() as cur:
            cur.execute("SELECT * FROM vessels WHERE ship_id = %s", (ship_id,))
            vessel = cur.fetchone()
            cur.execute(
                "SELECT * FROM positions WHERE ship_id = %s ORDER BY position_ts DESC LIMIT 1",
                (ship_id,),
            )
            pos = cur.fetchone()
            cur.execute(
                "SELECT * FROM voyages WHERE ship_id = %s ORDER BY last_seen_at DESC, id DESC LIMIT 1",
                (ship_id,),
            )
            voy = cur.fetchone()
        return {
            "vessel": dict(vessel) if vessel else None,
            "position": dict(pos) if pos else None,
            "voyage": dict(voy) if voy else None,
        }

    def track(self, ship_id, since=None, limit=None):
        """Returns ordered position history for one ship, for plotting a route."""
        query = "SELECT * FROM positions WHERE ship_id = %s"
        params = [ship_id]
        if since is not None:
            query += " AND position_ts >= %s"
            params.append(since)
        query += " ORDER BY position_ts ASC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        with self._cur() as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def export_table(self, table):
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table}")
            cols = [d.name for d in cur.description]
            rows = cur.fetchall()
        return cols, rows

    # ---- mainshipdata ------------------------------------------------------

    def get_all_mainshipdata(self, limit: int = 10, offset: int = 0):
        """Return rows from mainshipdata with optional pagination."""
        with self._cur() as cur:
            cur.execute(
                "SELECT * FROM mainshipdata ORDER BY id LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS total FROM mainshipdata")
            total = cur.fetchone()["total"]
        return [dict(r) for r in rows], total

    def upsert_mainshipdata(self, flat_row):
        """Insert or update one flat dict (keyed by CSV column names) into mainshipdata."""
        params = {c: flat_row.get(c) for c in MSD_COLS}
        params["synced_at"] = now_utc()
        with self.conn.cursor() as cur:
            cur.execute(MSD_INSERT, params)
        self.conn.commit()

    # ---- ship inventory (slim view for external consumers) -----------------

    def get_ship_inventory(self, limit: int = 10, offset: int = 0):
        """Return the slim ship-inventory projection of mainshipdata with pagination."""
        with self._cur() as cur:
            cur.execute(
                """SELECT
                    vessel_ship_id AS ship_id,
                    COALESCE(vessel_name, vessel_ais_name) AS vessel_name,
                    voyage_departure_port_name,
                    voyage_departure_utc,
                    voyage_departure_label,
                    voyage_arrival_port_name,
                    COALESCE(voyage_eta_utc, voyage_arrival_utc) AS voyage_eta_utc,
                    position_area_name AS current_area,
                    position_area_code AS area_code,
                    vessel_type,
                    COALESCE(vessel_subtype, vessel_type) AS vessel_subtype,
                    vessel_updated_at
                FROM mainshipdata
                ORDER BY id
                LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS total FROM mainshipdata")
            total = cur.fetchone()["total"]
        return [dict(r) for r in rows], total

    def search_ship_inventory(self, q: str, limit: int = 10, offset: int = 0):
        """Fuzzy-search the ship-inventory projection by vessel name or ship id.

        Uses pg_trgm similarity (typo-tolerant) OR'd with a plain substring
        match, so both "near enough" spellings and partial id/name fragments
        are found. Results are ranked by match score, best first.
        """
        like_q = f"%{q}%"
        with self._cur() as cur:
            cur.execute(
                """WITH matches AS (
                    SELECT
                        vessel_ship_id AS ship_id,
                        COALESCE(vessel_name, vessel_ais_name) AS vessel_name,
                        voyage_departure_port_name,
                        voyage_departure_utc,
                        voyage_departure_label,
                        voyage_arrival_port_name,
                        COALESCE(voyage_eta_utc, voyage_arrival_utc) AS voyage_eta_utc,
                        position_area_name AS current_area,
                        position_area_code AS area_code,
                        vessel_type,
                        COALESCE(vessel_subtype, vessel_type) AS vessel_subtype,
                        vessel_updated_at,
                        GREATEST(
                            similarity(COALESCE(vessel_name, ''), %(q)s),
                            similarity(COALESCE(vessel_ais_name, ''), %(q)s),
                            similarity(CAST(vessel_ship_id AS TEXT), %(q)s)
                        ) AS score
                    FROM mainshipdata
                    WHERE
                        similarity(COALESCE(vessel_name, ''), %(q)s) > 0.15
                        OR similarity(COALESCE(vessel_ais_name, ''), %(q)s) > 0.15
                        OR similarity(CAST(vessel_ship_id AS TEXT), %(q)s) > 0.15
                        OR vessel_name ILIKE %(like_q)s
                        OR vessel_ais_name ILIKE %(like_q)s
                        OR CAST(vessel_ship_id AS TEXT) ILIKE %(like_q)s
                )
                SELECT *, COUNT(*) OVER() AS total_count
                FROM matches
                ORDER BY score DESC, vessel_name ASC
                LIMIT %(limit)s OFFSET %(offset)s""",
                {"q": q, "like_q": like_q, "limit": limit, "offset": offset},
            )
            rows = [dict(r) for r in cur.fetchall()]
        total = rows[0].pop("total_count") if rows else 0
        for r in rows:
            r.pop("total_count", None)
        return rows, total
