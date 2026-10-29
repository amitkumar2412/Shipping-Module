# Spring Boot Migration Prompt — Shipping Scraper GET API

This document is a self-contained prompt/spec for recreating the existing FastAPI
read-only API ([api.py](../api.py)) as a Spring Boot service. Paste the "Prompt to
use later" section into a new session when the Spring Boot work starts; the
reference section below it captures everything needed to reproduce behavior
exactly (SQL, pagination rules, response shapes).

---

## Prompt to use later

> Build a Spring Boot REST API that exactly replicates the three read-only
> endpoints described below, which currently exist as a FastAPI service backed
> by PostgreSQL. Preserve the same paths, query parameters, validation rules,
> SQL semantics, and JSON response shapes byte-for-byte compatible with the
> original (field names and nesting must match). Use Spring Data JPA or
> JdbcTemplate with native queries (the fuzzy-search endpoint depends on the
> PostgreSQL `pg_trgm` extension, which must stay enabled). Do not implement
> any write/ingestion endpoints — this is a read-only projection service.
> Project should use: `spring-boot-starter-web`, `spring-boot-starter-data-jpa`
> (or `spring-boot-starter-jdbc`), `org.postgresql:postgresql`,
> `spring-boot-starter-validation`. Config via `application.yml` reading
> `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` env vars (same
> names as the Python `.env`). Use a connection pool (HikariCP, Spring Boot's
> default) instead of a single shared connection.

---

## Current flow (FastAPI → Postgres)

```
Client
  │  HTTP GET /mainshipdata?limit=&offset=
  ▼
Uvicorn (ASGI server)
  ▼
FastAPI route function (api.py)
  │  - fastapi.Query() validates/coerces limit, offset, q
  │  - defaults: limit=10 (max 10, min 1), offset=0 (min 0)
  ▼
Store method (database/store.py) — single shared psycopg2 connection,
  │  cursor_factory=RealDictCursor
  │  - runs one parameterized SELECT ... LIMIT/OFFSET query
  │  - runs a second COUNT(*) query for the total
  ▼
PostgreSQL (db "chemos_dev", table "mainshipdata")
  ▼
rows → list[dict] via RealDictCursor
  ▼
route wraps rows in a JSON envelope: {total, limit, offset, data}
  ▼
FastAPI serializes dict → JSON (no explicit Pydantic response_model)
  ▼
HTTP 200 JSON response → Client
```

There is no auth, no explicit error handling (uncaught exceptions fall through
to FastAPI's default 500), and the app holds one long-lived DB connection
opened at startup (`store = Store()` at module import time) rather than a
pool — this is a gap worth fixing in the Spring Boot version (HikariCP).

---

## Endpoint reference

### 1. `GET /mainshipdata`

Full-width dump of the `mainshipdata` table (one flattened row per ship,
combining vessel/position/voyage data — see schema below), paginated.

**Query params**
| name | type | constraints | default |
|---|---|---|---|
| `limit` | int | `1 <= limit <= 10` | `10` |
| `offset` | int | `offset >= 0` | `0` |

**SQL**
```sql
SELECT * FROM mainshipdata ORDER BY id LIMIT :limit OFFSET :offset;
SELECT COUNT(*) AS total FROM mainshipdata;
```

**Response**
```json
{
  "total": 123,
  "limit": 10,
  "offset": 0,
  "data": [ { /* every column of mainshipdata, see schema */ } ]
}
```

---

### 2. `GET /ship-inventory`

Slim projection of `mainshipdata`, paginated — same params/defaults as above.

**SQL**
```sql
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
    vessel_updated_at
FROM mainshipdata
ORDER BY id
LIMIT :limit OFFSET :offset;

SELECT COUNT(*) AS total FROM mainshipdata;
```

**Response**
```json
{
  "total": 123,
  "limit": 10,
  "offset": 0,
  "data": [
    {
      "ship_id": 304617,
      "vessel_name": "BOW TRAJECTORY",
      "voyage_departure_port_name": "...",
      "voyage_departure_utc": "...",
      "voyage_departure_label": "...",
      "voyage_arrival_port_name": "...",
      "voyage_eta_utc": "...",
      "current_area": "...",
      "area_code": "...",
      "vessel_type": "...",
      "vessel_subtype": "...",
      "vessel_updated_at": "..."
    }
  ]
}
```

---

### 3. `GET /ship-inventory/search`

Fuzzy search over the same projection, typo-tolerant via PostgreSQL's
`pg_trgm` extension (`CREATE EXTENSION IF NOT EXISTS pg_trgm` — already
applied in [database/schema.py](../database/schema.py), and two trigram GIN
indexes exist on `vessel_name` / `vessel_ais_name`). Combines:
- trigram `similarity()` score (threshold `> 0.15`) across vessel name,
  AIS name, and ship id cast to text, and
- a plain `ILIKE '%q%'` substring fallback,

so both near-spellings ("Evergren") and partial ids/names match. Results are
ranked by best match score, then vessel name.

**Query params**
| name | type | constraints | default |
|---|---|---|---|
| `q` | string | required, `min_length=1` | — |
| `limit` | int | `1 <= limit <= 10` | `10` |
| `offset` | int | `offset >= 0` | `0` |

**SQL**
```sql
WITH matches AS (
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
            similarity(COALESCE(vessel_name, ''), :q),
            similarity(COALESCE(vessel_ais_name, ''), :q),
            similarity(CAST(vessel_ship_id AS TEXT), :q)
        ) AS score
    FROM mainshipdata
    WHERE
        similarity(COALESCE(vessel_name, ''), :q) > 0.15
        OR similarity(COALESCE(vessel_ais_name, ''), :q) > 0.15
        OR similarity(CAST(vessel_ship_id AS TEXT), :q) > 0.15
        OR vessel_name ILIKE :like_q
        OR vessel_ais_name ILIKE :like_q
        OR CAST(vessel_ship_id AS TEXT) ILIKE :like_q
)
SELECT *, COUNT(*) OVER() AS total_count
FROM matches
ORDER BY score DESC, vessel_name ASC
LIMIT :limit OFFSET :offset;
```
`:like_q` = `"%" + q + "%"`. The window-function `total_count` is read off the
first returned row (or `0` if no rows matched) and stripped from each row
before building the response — in Spring Boot, map it to a separate field in
the result set projection rather than exposing it on the DTO.

**Response**
```json
{
  "query": "bow",
  "total": 7,
  "limit": 10,
  "offset": 0,
  "data": [ { /* same 12 fields as /ship-inventory, no score/total_count */ } ]
}
```

---

## `mainshipdata` schema (for the full-dump endpoint and Entity/DTO mapping)

One row per ship (`vessel_ship_id UNIQUE`), flattening three logical groups —
`vessel_*`, `position_*`, `voyage_*` — plus `id` (PK) and `synced_at`. Full
column list and types: see [database/schema.py](../database/schema.py) lines
140–227 (`mainshipdata` table) and `MSD_COLS` (insertion-order column list).

---

## Notes for the Spring Boot implementation

- **Response envelope** `{total, limit, offset, data}` (plus `query` on the
  search endpoint) must be identical — define one generic `PagedResponse<T>`
  DTO.
- **Pagination defaults/bounds** (`limit` 1–10 default 10, `offset` ≥0 default
  0) should be enforced with `@Min`/`@Max` on the controller params, returning
  the same 422-style validation behavior FastAPI gives for out-of-range values.
- **`pg_trgm`** must remain enabled in whatever Postgres instance the Spring
  Boot app points at — don't let a migration tool (Flyway/Liquibase) skip it.
- This spec intentionally excludes the scraper/ingestion side (`main.py`,
  `cli.py`, `scraper.py`, `store.save`, `upsert_mainshipdata`) — those stay in
  Python; only the three GET endpoints above are in scope for the Spring Boot
  port.
