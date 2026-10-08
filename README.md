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
- Node 22.12+ (developed on 24). The installed vitest requires Node ^22.12 || ^24 || >=26, so Node 20 and odd-numbered 23/25 will not work for `npm test`.
- PostgreSQL with PostGIS (developed on PostgreSQL 18 + PostGIS 3.6)

## One-time setup (Windows)

1. Create two databases, `vessel_tracker` and `vessel_tracker_test`, and run this in each (you do this yourself; the project never creates databases):

   ```sql
   CREATE EXTENSION IF NOT EXISTS postgis;
   ```

2. Set three environment variables with `setx` (same syntax in PowerShell and cmd.exe) or System Properties > Environment Variables, then restart the terminal (and Claude Code, if you use it). `setx` does not affect the window you ran it in, only windows opened afterwards:

   - `DATABASE_URL` - connection URL for `vessel_tracker`
   - `TEST_DATABASE_URL` - connection URL for `vessel_tracker_test`
   - `AISSTREAM_API_KEY` - free key from https://aisstream.io

   URL-encode special characters in the database password. Never commit these values: `.env*` is git-ignored and the code reads only environment variables.

3. Create the virtualenv outside the repo (the repo is in OneDrive), activate it, and install. Run these from the repo root. The shell matters: `%LOCALAPPDATA%` is only expanded by cmd.exe; in PowerShell it would create a literal `%LOCALAPPDATA%` folder in the current directory.

   PowerShell:

   ```
   python -m venv $env:LOCALAPPDATA\vessel-tracker-venv
   & "$env:LOCALAPPDATA\vessel-tracker-venv\Scripts\Activate.ps1"
   pip install -e ".[dev]"
   ```

   If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

   cmd.exe:

   ```
   python -m venv %LOCALAPPDATA%\vessel-tracker-venv
   %LOCALAPPDATA%\vessel-tracker-venv\Scripts\activate.bat
   pip install -e ".[dev]"
   ```

   Without activating, call the interpreter directly, e.g. in PowerShell `& "$env:LOCALAPPDATA\vessel-tracker-venv\Scripts\python.exe" -m pytest`.

4. Install the front end:

   ```
   cd web
   npm install
   ```

   (`cd` and `npm` are the same in both shells.)

5. Apply the schema (from the repo root, virtualenv active):

   ```
   python -m db.migrate
   python -m db.migrate --test
   ```

## Run

Three terminals (PowerShell or cmd.exe; the commands are identical in both), each from the repo root with the virtualenv activated in it. The third runs Node and needs no virtualenv.

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

### If something is wrong

- `RuntimeError: AISSTREAM_API_KEY environment variable is not set` (or the same for `DATABASE_URL`) at startup: the variable is missing in this terminal. Set it with `setx` and open a NEW terminal.
- `AISstream error frame: ...`: AISstream rejected the request, typically a bad or rate-limited key. Check the key at aisstream.io. The key is redacted in this line. It is logged on the first error per connection, then at most once a minute.
- `AISstream connection lost (...); reconnecting` repeating: a network, proxy or firewall is blocking websockets, or the service is down. The collector retries with backoff up to 60 s.
- `AISstream subscription confirmed` never appears: the connection is not completing or the key is not accepted; look for the two messages above. `AISstream first message received` shows whether any frame arrived at all.
- Heartbeat `received` stays flat: no feed is reaching the collector.
- `received` rises but `known_tankers` stays 0 for several minutes: frames arrive but none parse (look for `dropped message (total dropped=...)` warnings, which are rate-limited). Compare a live frame with `tests/fixtures/aisstream_real_frames.json`. This exact failure happened once when AISstream's `MetaData` key was misread.
- Database connection errors (`database reconnect failed (...); retrying in ... s`): the collector retries with backoff and logs `database reconnected` on success. Check that PostgreSQL is running and `DATABASE_URL` is right.

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
- At zoom 5 and above, individual markers appear, and the status chip shows Live with a recent age. Below zoom 5 the chip reads "Zoom in for live updates".
- Changing filters changes the counts.
- Clicking a vessel opens the detail panel.
- The track buttons show a track.

## Tuning classification

Edit `config/classification.yaml`. The values are starting points, not calibrated.

- `size_classes`: listed largest first. A vessel gets the first class whose `min_length_m` is at or below its reported length. Each class carries a `cargo_group` (crude, mostly_crude, crude_or_products, mostly_products, products, products_coastal) and a `laden_draught_m`. A vessel with no length is Unclassified / unknown.
- `laden_ratio`: laden if draught >= `laden_ratio` x the class `laden_draught_m`.
- `observed_range_min_m`: once a vessel's own observed min/max draught spans at least this much, laden means draught at or above the midpoint of that range instead of the class reference.
- `fade_hours`: the UI fades markers older than this. Restart the API after changing it (it reads the config).
- `stale_hours`: vessels older than this are hidden from the live map. Restart the API after changing it.
- `retention_months`: used by pruning.

Size class and laden changes apply per vessel: restart the collector, and each vessel is re-classified the next time it sends a static message (vessels that stay quiet keep their old class).

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

- Run the same two Python processes (collector and uvicorn) with environment variables set on the host: `DATABASE_URL` for both processes, `AISSTREAM_API_KEY` for the collector only. `TEST_DATABASE_URL` is only needed on dev machines.
- Build the UI with `npm run build`, serve `web/dist` as static files, and reverse-proxy `/api` and `/ws` to uvicorn, including the websocket upgrade for `/ws`.
- Add authentication in front before exposing it publicly; v1 has none.
- To change data feed, write a class implementing `collector.providers.base.AISProvider` (an async `messages()` yielding normalized messages) and use it in `collector/main.py` in place of `AISStreamProvider`. The collector heartbeat also reads `provider.received`, `provider.last_received` (a `time.monotonic()` value or `None`) and `provider.dropped`, so a replacement must expose those attributes. Paid options include Spire, MarineTraffic API, and S&P Global for cargo intelligence.

## Data source and privacy

`tests/fixtures/aisstream_real_frames.json` holds real public AIS frames (including vessel names and MMSIs) captured from AISstream for the parser tests. It contains no API key.
