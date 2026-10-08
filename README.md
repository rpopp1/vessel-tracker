# vessel-tracker

## What it is

A live map of tankers only (AIS ship type 80-89), for seeing where crude and refined products move by sea. A Python collector reads the AISstream feed into PostgreSQL/PostGIS, a FastAPI service serves it, and a React/Vite/MapLibre UI in `web/` draws it.

Limits to know before trusting the map:

- Cargo group (crude vs products) is INFERRED from vessel length (size class). AIS does not report cargo.
- Laden vs ballast is ESTIMATED from reported draught.
- The laden estimate is unreliable for very small tankers. The "Handy/small" reference draught (`laden_draught_m: 8.0` in `config/classification.yaml`) is too deep for small coastal and inland tankers, so many read as ballast. Tune it (see "Tuning classification").
- "Aframax/LR2" cannot be told apart by size; it is labelled `crude_or_products`.
- Chemical, LPG and LNG carriers share the 80-89 type codes and mix into the classes.
- Free AISstream coverage is patchy.
- Track history only exists from when the collector first ran.
- No authentication in v1.

## Prerequisites

- Python 3.11+ (developed on 3.14)
- Node 20+ (developed on 24)
- PostgreSQL with PostGIS (developed on PostgreSQL 18 + PostGIS 3.6)

## One-time setup (Windows)

1. Create two databases, `vessel_tracker` and `vessel_tracker_test`, and run this in each (you do this yourself; the project never creates databases):

   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```

2. Set three environment variables (`setx`, or System Properties > Environment Variables), then restart the terminal (and Claude Code, if you use it):

   - `DATABASE_URL` - connection URL for `vessel_tracker`
   - `TEST_DATABASE_URL` - connection URL for `vessel_tracker_test`
   - `AISSTREAM_API_KEY` - free key from https://aisstream.io

   URL-encode special characters in the database password. Never commit these values: `.env*` is git-ignored and the code reads only environment variables.

3. Create the virtualenv outside the repo (the repo is in OneDrive), activate it, and install:

   ```
   python -m venv %LOCALAPPDATA%\vessel-tracker-venv
   %LOCALAPPDATA%\vessel-tracker-venv\Scripts\activate
   pip install -e ".[dev]"
   ```

4. Install the front end:

   ```
   cd web
   npm install
   ```

5. Apply the schema (from the repo root, virtualenv active):

   ```
   python -m db.migrate
   python -m db.migrate --test
   ```

## Run

Three terminals, each from the repo root with the virtualenv active (except the third).

1. Collector:

   ```
   python -m collector.main
   ```

   It logs a heartbeat every 60 s. Look for these lines:

   - `AISstream connected` - websocket is open
   - `AISstream subscription confirmed` - the feed accepted your key and is sending data
   - `heartbeat known_tankers=... received=... dropped=... last_frame=... handler_errors=...` - counters; `received` should climb and `last_frame` stay small

   `known_tankers` grows over the first minutes. Positions are stored only for vessels whose static message has been seen, so the map fills in gradually.

2. API:

   ```
   python -m uvicorn api.main:create_app --factory --port 8000
   ```

3. Web UI:

   ```
   cd web
   npm run dev
   ```

   Open the URL it prints. The dev server proxies `/api` and `/ws` to `127.0.0.1:8000`. If port 8000 is taken, run uvicorn on another port and change both proxy targets in `web/vite.config.ts`.

## Tests

```
python -m pytest -rs
cd web
npm test
npm run build
```

DB tests need `TEST_DATABASE_URL` set and the test DB migrated (`python -m db.migrate --test`); otherwise they skip. `-rs` prints the skip reasons so you can notice them.

The automated tests do NOT cover the map's visual rendering or live websocket behavior. Those were never verified in a browser during the build. Check by hand the first time:

- The map loads.
- At low zoom, vessels appear as clusters.
- At zoom 5 and above, individual markers appear.
- Changing filters changes the counts.
- Clicking a vessel opens the detail panel.
- The track buttons show a track.
- The status chip shows Live and a recent age.

## Tuning classification

Edit `config/classification.yaml`. The values are starting points, not calibrated.

- `size_classes`: listed largest first. A vessel gets the first class whose `min_length_m` is at or below its reported length. Each class carries a `cargo_group` (crude, mostly_crude, crude_or_products, mostly_products, products, products_coastal) and a `laden_draught_m`. A vessel with no length is Unclassified / unknown.
- `laden_ratio`: laden if draught >= `laden_ratio` x the class `laden_draught_m`.
- `observed_range_min_m`: once a vessel's own observed min/max draught spans at least this much, laden means draught at or above the midpoint of that range instead of the class reference.
- `fade_hours`: the UI fades markers older than this.
- `stale_hours`: vessels older than this are hidden from the live map.
- `retention_months`: used by pruning.

Classification is computed from each vessel's static message, so after you edit the file and restart the collector, a vessel is re-classified the next time it sends a static message.

## Data retention

`positions` is partitioned by month; the collector creates upcoming partitions automatically (at startup and hourly). To drop partitions older than `retention_months`:

```
python -m db.prune --yes
python -m db.prune --yes --test
```

This is destructive: it deletes history. Without `--yes` it refuses to run. `--test` targets the test DB.

## OneDrive note

The repo sits in OneDrive. Keep the virtualenv outside it (as above). `web/node_modules` is large, so pause OneDrive sync during `npm install`, or move the project outside OneDrive.

## Hosting later

- Run the same two Python processes (collector and uvicorn) with the same three environment variables set on the host.
- Build the UI with `npm run build`, serve `web/dist` as static files, and reverse-proxy `/api` and `/ws` to uvicorn, including the websocket upgrade for `/ws`.
- Add authentication in front before exposing it publicly; v1 has none.
- To change data feed, write a class implementing `collector.providers.base.AISProvider` (an async `messages()` yielding normalized messages) and use it in `collector/main.py` in place of `AISStreamProvider`. Paid options include Spire, MarineTraffic API, and S&P Global for cargo intelligence.

## Data source and privacy

`tests/fixtures/aisstream_real_frames.json` holds real public AIS frames (including vessel names and MMSIs) captured from AISstream for the parser tests. It contains no API key.
