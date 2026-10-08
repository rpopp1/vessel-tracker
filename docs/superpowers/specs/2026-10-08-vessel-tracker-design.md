# Vessel Tracker — Design Spec

Date: 2026-10-08
Status: Draft for review

## 1. Purpose and scope

A MarineTraffic-style live map of tanker traffic, used to see where crude oil and refined products (diesel, etc.) are moving by sea. Intended users: Ryan and the Karbone team, for market and supply analysis.

**Decisions made**
- Data: start with free AIS (AISstream.io websocket). The data layer must be swappable for a paid provider (Spire, MarineTraffic API, S&P Global, etc.) later.
- Coverage: global, **tankers only** (AIS ship type codes 80-89). Non-tankers are discarded at ingestion.
- Runtime: local first (Windows machine), architected so hosting later is a deploy step, not a rewrite.
- Stack: Python (FastAPI) backend, PostgreSQL + PostGIS, React + Vite + MapLibre front end.
- Required feature: a breakdown of tanker types with filtering by it.

**Limits to be honest about in the UI and docs**
- "Identical to MarineTraffic" is not achievable: it depends on a global receiver network and years of history. v1 matches the map UI and core features, constrained by free-feed coverage.
- AIS does not report cargo. Crude vs. products is an **inferred** tag based on vessel size class and is labelled as such.
- Laden vs. ballast is estimated from draught and is labelled as such.
- Free AIS has patchy coverage in open ocean and some regions.
- History only exists from the time the collector starts running.

**Out of scope for v1:** port-call detection, voyage/ETA analytics, alerts, user accounts, paid data sources, distinguishing chemical/LPG/LNG carriers from oil tankers.

## 2. Architecture

Two processes sharing PostgreSQL:

```
AISstream (websocket)
        |
   [ Collector ]   provider interface: AISStreamProvider now; others later
        |  filter to tankers, normalize, classify
        v
   PostgreSQL + PostGIS
   - vessels, positions (time series), latest_position
        |
   [ API (FastAPI) ]  REST + websocket
        |
   [ React + MapLibre UI ]
```

- Collector and API are independent: restarting one does not affect the other.
- Collector depends only on an `AISProvider` interface yielding normalized position and static-data messages. Swapping the feed means one new provider class.
- No message queue in v1 (YAGNI).

## 3. Data model

| Table | Key columns | Notes |
|---|---|---|
| `vessels` | `mmsi` (PK), `imo`, `name`, `callsign`, `flag`, `ship_type_code`, `length_m`, `beam_m`, `size_class`, `cargo_group`, `classified_by`, `updated_at` | From AIS static data (message types 5 and 24). `classified_by` records the source (`dimensions`, `manual`, ...) so better sources can override without losing the original. |
| `positions` | `mmsi`, `ts`, `geom` (PostGIS point), `sog`, `cog`, `heading`, `nav_status`, `draught_m` | Time series, partitioned by month; indexed on `(mmsi, ts)` and `geom`. Old data pruned/downsampled on a schedule. |
| `latest_position` | same fields, one row per vessel | Updated per message; the map reads this, never scans history. |

A vessel is stored only once its ship type code is known to be 80-89. Tankers lacking static data (dimensions) display as "unclassified tanker" until it arrives.

## 4. Classification

One module, thresholds in `config/`, run on first static message per vessel (re-run if dimensions change).

| Size class | Approx. length | Cargo group (inferred) |
|---|---|---|
| ULCC / VLCC | > 300 m | Crude |
| Suezmax | 260-300 m | Mostly crude |
| Aframax / LR2 | 225-260 m | Crude or products (unknown) |
| Panamax / LR1 | 200-225 m, beam ~32 m | Mostly products |
| MR | 160-200 m | Products |
| Handy and small | < 160 m | Products / coastal |

- Aframax and LR2 are the same size; dimensions cannot separate them.
- Chemical, LPG and LNG carriers share codes 80-89 and will mix into these classes in v1. Fix later via IMO registry lookup or a paid source.
- Laden/ballast: current draught vs. typical laden draught for the size class, refined by the vessel's own observed min/max over time.
- Thresholds are starting values to be tuned against real data.

## 5. API

| Endpoint | Purpose |
|---|---|
| `GET /api/vessels` | Current positions as GeoJSON. Params: bbox, `size_class`, `cargo_group`, `laden`, `flag`, `nav_status`, speed range. Returns clusters when zoomed out, individual vessels when zoomed in. |
| `GET /api/vessels/{mmsi}` | Static data, classification and how it was derived, latest position. |
| `GET /api/vessels/{mmsi}/track?from=&to=` | Position history as a line, downsampled for long ranges. |
| `GET /api/search?q=` | Name, MMSI or IMO search. |
| `GET /api/stats` | Counts by size class, cargo group, laden/ballast (feeds the breakdown panel). |
| `WS /ws/positions` | Client sends bbox + filters; server pushes only matching changes. |

## 6. UI

- **Map:** dark ocean basemap; markers colored by size class, rotated to course; laden = solid, ballast = hollow; unclassified = grey.
- **Left panel:** breakdown by size class with live counts; clicking toggles the filter. Further filters: cargo group, laden/ballast, flag, nav status. Counts update with filters.
- **Top:** search by name, MMSI or IMO; jumps to and opens the vessel.
- **Right panel (on click):** name, flag, size class, dimensions, speed, course, draught, destination, ETA, last seen; inferred values tagged "inferred"; track toggle (24h / 7d / 30d, limited to collected history).
- **Status chip:** feed connection state and age of the newest message.

## 7. Error handling

- Collector: reconnect with backoff, log gaps; drop malformed/out-of-range messages and count them.
- API/UI: explicit empty states ("no vessels match these filters").
- Stale vessels (no message for 6 h by default, configurable) fade and are then hidden from the live map; history is kept.

## 8. Testing

- Unit tests: classifier (sample dimensions per class), message normalizer (recorded AISstream sample messages).
- API tests against a throwaway test database.
- Manual end-to-end smoke test against the live feed.

## 9. Layout and local setup

```
vessel-tracker/
  collector/   providers/ (base.py, aisstream.py), classify.py, main.py
  api/
  db/          schema and migrations
  web/         React + Vite + MapLibre
  tests/
  config/      classification thresholds, stale-data limits
  docs/superpowers/specs/
  README.md
```

- Python virtual environment for collector and API; PostgreSQL + PostGIS installed locally.
- `AISSTREAM_API_KEY` supplied via environment variable; never hardcoded, printed or logged.
- Run: collector process, API process, `npm run dev` for the UI.
- The project lives in OneDrive. The virtual environment, `node_modules` and any database files must be excluded from sync (documented in the README).

**Org policy constraints on the build (Karbone):**
- Database creation (`createdb`, PostGIS extension setup) is run by the human; Claude supplies the commands.
- Database migrations require explicit human confirmation in the session each time.
- Claude asks for confirmation before writing the first code that connects to AISstream.
- `.env*` files and credentials are never read or written by Claude.

## 10. Build order

1. Database schema and migrations
2. Classifier with tests
3. Provider interface, AISstream provider and normalizer, tested on recorded samples
4. Collector writing live data to Postgres
5. API endpoints
6. UI: map and markers, then filter/breakdown panel, then vessel panel and tracks
7. Websocket live updates, stale handling, status chip
8. README and hosting-later notes (two processes, environment variables)
