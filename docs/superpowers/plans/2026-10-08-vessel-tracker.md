# Vessel Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local-first, hostable-later live map of global tanker traffic (size-class breakdown, filters, vessel details, tracks) fed by free AIS data behind a swappable provider interface.

**Architecture:** Two Python processes share PostgreSQL/PostGIS. The *collector* reads AISstream over a websocket, keeps only tankers (AIS ship type 80-89), classifies them by length, and writes `vessels`, `positions` and `latest_position`. The *API* (FastAPI) serves GeoJSON, stats, search and tracks over REST plus a polling-based websocket. A React + Vite + MapLibre UI consumes both.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, psycopg 3 (+ psycopg_pool), websockets >= 13, PyYAML, pytest (+ pytest-asyncio, httpx); PostgreSQL + PostGIS; React + TypeScript + Vite, maplibre-gl, vitest.

**Spec:** `docs/superpowers/specs/2026-10-08-vessel-tracker-design.md`

## Global Constraints

- Tankers only: keep a vessel only when AIS ship type code is 80-89. Discard everything else at ingestion.
- Size classes and starting length thresholds (tunable in `config/classification.yaml`): ULCC/VLCC > 300 m, Suezmax 260-300 m, Aframax/LR2 225-260 m, Panamax/LR1 200-225 m, MR 160-200 m, Handy/small < 160 m.
- Cargo group and laden/ballast are **inferred**; the UI must label them "inferred"/"estimated".
- Stale vessels: hidden from the live map after 6 h without a message (default, configurable); history kept. Fade before that (default 2 h).
- Track presets: 24h / 7d / 30d, limited to collected history.
- Endpoints: `GET /api/vessels`, `GET /api/vessels/{mmsi}`, `GET /api/vessels/{mmsi}/track?from=&to=`, `GET /api/search?q=`, `GET /api/stats`, `WS /ws/positions`.
- Secrets: `AISSTREAM_API_KEY`, `DATABASE_URL`, `TEST_DATABASE_URL` come from environment variables only. Never hardcode, print, or log them. Never read or write `.env*` files or other credential files. The human sets these variables in their own shell before launching Claude Code.
- Karbone policy gates (marked **GATE** below; stop and ask the human, do not proceed on a previous approval):
  - The human runs `createdb`/`CREATE DATABASE` and any superuser extension setup; Claude only supplies the commands.
  - Every migration run (`python -m db.migrate`, including `--test`) needs explicit confirmation in the current session.
  - Confirm before writing the first code in a file that connects to an external network service (AISstream in `collector/providers/aisstream.py`; the map tile service in the web app).
  - No force-push, hard reset, or `terraform` commands.
- Commit messages end with: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Project lives in OneDrive: keep the Python virtualenv outside the repo (see Task 1).

## Spec clarifications made by this plan

- `vessels` also stores `draught_m`, `draught_min_m`, `draught_max_m`, `laden`, `destination`, `eta` (the detail panel and laden filter need them).
- AIS message type 24 (Class B static) is not handled in v1; tankers are Class A (type 5, delivered by AISstream as `ShipStaticData`).
- Position reports carry no ship type, so the collector drops positions for MMSIs it has not yet seen a tanker static message for. Static messages repeat about every 6 minutes, so vessels appear shortly after the collector starts.
- Size class uses length only in v1 (beam is stored but not used).
- `GET /api/meta` (class list, fade/stale hours) is added for the UI; `GET /api/stats` also returns `newest_ts` for the status chip.
- Flag is derived from the MMSI's Maritime Identification Digits (MID) using a table of the major tanker flags; other MIDs show "Other".

## Review Focus

1. A tanker whose static message has not arrived, or never arrives (positions must be dropped, not stored, not crash) - Task 6.
2. Views and tracks crossing the antimeridian (bbox with west > east; track must not draw a line across the whole map) - Tasks 7, 10.
3. AIS "not available" and zero values: Sog 102.3, Cog 360, heading 511, lat 91/lon 181, 0/0 position, dimensions 0, ETA month 0, empty names (must become `None`/"Unclassified", never crash) - Task 4.
4. Stale vessels: hidden from map and counts but their tracks and detail still load - Task 7.
5. Search and lookups with empty, 1-character, wildcard (`%`, `_`), very long digit, or unknown input; unknown MMSI returns 404 - Tasks 7, 8.

---

## File Structure

```
pyproject.toml
config/classification.yaml
common/{__init__,config,database,models,flags}.py
collector/{__init__,classify,pipeline,store,main}.py
collector/providers/{__init__,base,aisstream_parse,aisstream}.py
db/{__init__,migrate,partitions,prune}.py
db/migrations/001_init.sql
api/{__init__,filters,queries,main}.py
tests/{__init__,conftest,helpers,samples}.py
tests/test_*.py
web/                      (Vite app: src/{main,App,api,types,filters,colors}.ts(x), src/components/*, src/useLiveSocket.ts)
README.md
```

---

### Task 1: Project scaffold, config loader, DB helper

**Files:**
- Create: `pyproject.toml`, `config/classification.yaml`, `common/__init__.py`, `common/config.py`, `common/database.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `common.config.load_config(path=None) -> Config`; `Config(size_classes: tuple[SizeClass,...], laden_ratio, observed_range_min_m, fade_hours, stale_hours, retention_months)`; `SizeClass(name, min_length_m, cargo_group, laden_draught_m)` (tuple sorted largest first). `common.database.database_url(test=False) -> str`, `connect(test=False) -> psycopg.Connection` (autocommit). Pytest fixtures `db_ready` (skips if `TEST_DATABASE_URL` unset) and `db` (connection to the test DB with tables truncated).

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "vessel-tracker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "psycopg[binary,pool]>=3.1",
  "websockets>=13",
  "pyyaml>=6",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27"]

[tool.setuptools.packages.find]
include = ["common*", "collector*", "api*", "db*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `config/classification.yaml`**

```yaml
# Size classes, largest first. A vessel gets the first class whose min_length_m <= its length.
size_classes:
  - {name: "ULCC/VLCC",   min_length_m: 300, cargo_group: crude,             laden_draught_m: 18.0}
  - {name: "Suezmax",     min_length_m: 260, cargo_group: mostly_crude,      laden_draught_m: 15.5}
  - {name: "Aframax/LR2", min_length_m: 225, cargo_group: crude_or_products, laden_draught_m: 13.0}
  - {name: "Panamax/LR1", min_length_m: 200, cargo_group: mostly_products,   laden_draught_m: 12.0}
  - {name: "MR",          min_length_m: 160, cargo_group: products,          laden_draught_m: 10.5}
  - {name: "Handy/small", min_length_m: 0,   cargo_group: products_coastal,  laden_draught_m: 8.0}

laden_ratio: 0.8            # laden if draught >= ratio * class laden draught
observed_range_min_m: 3.0   # use the vessel's own min/max draught once the range is at least this wide
fade_hours: 2               # UI fades markers older than this
stale_hours: 6              # hidden from the live map after this
retention_months: 3         # position partitions older than this can be pruned
```

- [ ] **Step 3: Write the failing test `tests/test_config.py`**

```python
from common.config import load_config


def test_default_config_loads_sorted_largest_first():
    cfg = load_config()
    names = [c.name for c in cfg.size_classes]
    assert names[0] == "ULCC/VLCC"
    assert names[-1] == "Handy/small"
    lengths = [c.min_length_m for c in cfg.size_classes]
    assert lengths == sorted(lengths, reverse=True)
    assert cfg.stale_hours == 6
    assert cfg.fade_hours == 2
```

- [ ] **Step 4: Create `tests/__init__.py` (empty) and run the test to verify it fails**

Run: `python -m pytest tests/test_config.py -v` (after Step 7's install; if the venv is not yet created, do Step 7 first).
Expected: FAIL with `ModuleNotFoundError: No module named 'common'`.

- [ ] **Step 5: Create `common/__init__.py` (empty) and `common/config.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "classification.yaml"


@dataclass(frozen=True)
class SizeClass:
    name: str
    min_length_m: float
    cargo_group: str
    laden_draught_m: float


@dataclass(frozen=True)
class Config:
    size_classes: tuple[SizeClass, ...]
    laden_ratio: float
    observed_range_min_m: float
    fade_hours: float
    stale_hours: float
    retention_months: int


def load_config(path: Path | str | None = None) -> Config:
    raw = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    classes = sorted((SizeClass(**c) for c in raw["size_classes"]), key=lambda c: -c.min_length_m)
    return Config(
        size_classes=tuple(classes),
        laden_ratio=float(raw["laden_ratio"]),
        observed_range_min_m=float(raw["observed_range_min_m"]),
        fade_hours=float(raw["fade_hours"]),
        stale_hours=float(raw["stale_hours"]),
        retention_months=int(raw["retention_months"]),
    )
```

- [ ] **Step 6: Create `common/database.py` and `tests/conftest.py`**

```python
# common/database.py
from __future__ import annotations

import os

import psycopg


def database_url(test: bool = False) -> str:
    name = "TEST_DATABASE_URL" if test else "DATABASE_URL"
    url = os.environ.get(name)
    if not url:
        raise RuntimeError(f"{name} environment variable is not set")
    return url


def connect(test: bool = False) -> psycopg.Connection:
    return psycopg.connect(database_url(test), autocommit=True)
```

```python
# tests/conftest.py
import psycopg.rows
import pytest

from common.database import connect, database_url


@pytest.fixture(scope="session")
def db_ready():
    try:
        database_url(test=True)
    except RuntimeError:
        pytest.skip("TEST_DATABASE_URL not set")


@pytest.fixture
def db(db_ready):
    conn = connect(test=True)
    conn.row_factory = psycopg.rows.dict_row  # rows are dicts, matching the API's connections
    conn.execute("TRUNCATE latest_position, positions, vessels CASCADE")
    yield conn
    conn.close()
```

- [ ] **Step 7: Create the virtualenv outside OneDrive and install**

Run (bash tool):
```bash
python -m venv "$LOCALAPPDATA/vessel-tracker-venv"
"$LOCALAPPDATA/vessel-tracker-venv/Scripts/python.exe" -m pip install -e ".[dev]"
```
Use `"$LOCALAPPDATA/vessel-tracker-venv/Scripts/python.exe"` as `python` for every Python command in this plan.

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml config common tests
git commit -m "feat: project scaffold, config loader and db helper"
```

---

### Task 2: Classifier, laden estimate, flag lookup

**Files:**
- Create: `collector/__init__.py`, `collector/classify.py`, `common/flags.py`, `tests/test_classify.py`, `tests/test_flags.py`

**Interfaces:**
- Consumes: `common.config.Config`.
- Produces: `collector.classify.Classification(size_class: str, cargo_group: str)`; `UNCLASSIFIED`; `is_tanker_type(code: int | None) -> bool`; `classify(length_m: float | None, cfg: Config) -> Classification`; `estimate_laden(size_class: str, draught_m: float | None, obs_min: float | None, obs_max: float | None, cfg: Config) -> bool | None`. `common.flags.flag_from_mmsi(mmsi: int) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_classify.py
import pytest

from collector.classify import UNCLASSIFIED, classify, estimate_laden, is_tanker_type
from common.config import load_config

CFG = load_config()


@pytest.mark.parametrize(
    "length,expected",
    [
        (333, "ULCC/VLCC"), (300, "ULCC/VLCC"), (299.9, "Suezmax"), (260, "Suezmax"),
        (259.9, "Aframax/LR2"), (225, "Aframax/LR2"), (224.9, "Panamax/LR1"), (200, "Panamax/LR1"),
        (199.9, "MR"), (160, "MR"), (159.9, "Handy/small"), (50, "Handy/small"),
    ],
)
def test_size_class_boundaries(length, expected):
    assert classify(length, CFG).size_class == expected


def test_cargo_group_follows_class():
    assert classify(333, CFG).cargo_group == "crude"
    assert classify(240, CFG).cargo_group == "crude_or_products"
    assert classify(180, CFG).cargo_group == "products"


@pytest.mark.parametrize("length", [None, 0, -5])
def test_missing_or_zero_length_is_unclassified(length):  # Review Focus 3
    assert classify(length, CFG) == UNCLASSIFIED


def test_tanker_type_codes():
    assert is_tanker_type(80) and is_tanker_type(89)
    assert not is_tanker_type(79) and not is_tanker_type(90)
    assert not is_tanker_type(None)


def test_laden_from_class_reference_when_no_history():
    # Suezmax reference 15.5 m * 0.8 = 12.4 m
    assert estimate_laden("Suezmax", 14.0, None, None, CFG) is True
    assert estimate_laden("Suezmax", 8.0, None, None, CFG) is False


def test_laden_uses_observed_range_when_wide_enough():
    assert estimate_laden("Suezmax", 13.0, 8.0, 16.0, CFG) is True   # above midpoint 12
    assert estimate_laden("Suezmax", 10.0, 8.0, 16.0, CFG) is False


def test_narrow_observed_range_is_ignored():
    # range 1 m < 3 m, so fall back to class reference (12.4 m)
    assert estimate_laden("Suezmax", 14.0, 13.5, 14.5, CFG) is True


@pytest.mark.parametrize("draught", [None, 0, 0.0])
def test_laden_unknown_without_draught(draught):
    assert estimate_laden("MR", draught, None, None, CFG) is None


def test_laden_unknown_for_unclassified():
    assert estimate_laden("Unclassified", 10.0, None, None, CFG) is None
```

```python
# tests/test_flags.py
from common.flags import flag_from_mmsi


def test_known_flags():
    assert flag_from_mmsi(351000000) == "Panama"
    assert flag_from_mmsi(636012345) == "Liberia"
    assert flag_from_mmsi(538000001) == "Marshall Islands"


def test_unknown_and_malformed_mmsi():
    assert flag_from_mmsi(999000000) == "Other"
    assert flag_from_mmsi(12345) == "Other"          # not a 9-digit vessel MMSI
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_classify.py tests/test_flags.py -v`
Expected: FAIL, `ModuleNotFoundError: collector`.

- [ ] **Step 3: Implement `collector/__init__.py` (empty), `collector/classify.py`, `common/flags.py`**

```python
# collector/classify.py
from __future__ import annotations

from dataclasses import dataclass

from common.config import Config


@dataclass(frozen=True)
class Classification:
    size_class: str
    cargo_group: str


UNCLASSIFIED = Classification("Unclassified", "unknown")


def is_tanker_type(code: int | None) -> bool:
    return code is not None and 80 <= code <= 89


def classify(length_m: float | None, cfg: Config) -> Classification:
    if not length_m or length_m <= 0:
        return UNCLASSIFIED
    for c in cfg.size_classes:
        if length_m >= c.min_length_m:
            return Classification(c.name, c.cargo_group)
    return UNCLASSIFIED


def estimate_laden(
    size_class: str,
    draught_m: float | None,
    obs_min: float | None,
    obs_max: float | None,
    cfg: Config,
) -> bool | None:
    if not draught_m or draught_m <= 0:
        return None
    if obs_min is not None and obs_max is not None and obs_max - obs_min >= cfg.observed_range_min_m:
        return draught_m >= (obs_min + obs_max) / 2
    ref = next((c.laden_draught_m for c in cfg.size_classes if c.name == size_class), None)
    if ref is None:
        return None
    return draught_m >= cfg.laden_ratio * ref
```

```python
# common/flags.py
from __future__ import annotations

# Maritime Identification Digits for the major tanker flags. Extend as needed.
_FLAGS = {
    "Panama": [351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374],
    "Liberia": [636, 637],
    "Marshall Islands": [538],
    "Singapore": [563, 564, 565, 566],
    "Malta": [215, 229, 248, 249, 256],
    "Hong Kong": [477],
    "Greece": [237, 239, 240, 241],
    "Bahamas": [308, 309, 311],
    "Cyprus": [209, 210, 212],
    "Norway": [257, 258, 259],
    "United Kingdom": [232, 233, 234, 235],
    "United States": [338, 366, 367, 368, 369],
    "China": [412, 413, 414],
    "India": [419],
    "Japan": [431, 432],
    "South Korea": [440, 441],
    "Russia": [273],
    "Denmark": [219, 220],
    "Germany": [211, 218],
    "Netherlands": [244, 245, 246],
    "Italy": [247],
    "France": [226, 227, 228],
    "Turkey": [271],
    "Saudi Arabia": [403],
    "United Arab Emirates": [470, 471],
    "Indonesia": [525],
    "Malaysia": [533],
    "Gibraltar": [236],
    "Isle of Man": [],
}
_MID = {mid: name for name, mids in _FLAGS.items() for mid in mids}


def flag_from_mmsi(mmsi: int) -> str:
    s = str(mmsi)
    if len(s) != 9:
        return "Other"
    return _MID.get(int(s[:3]), "Other")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_classify.py tests/test_flags.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add collector common tests
git commit -m "feat: size-class classifier, laden estimate and MID flag lookup"
```

---

### Task 3: Schema, migration runner, partitions, prune

**Files:**
- Create: `db/__init__.py`, `db/migrations/001_init.sql`, `db/migrate.py`, `db/partitions.py`, `db/prune.py`, `tests/test_partitions.py`, `tests/test_schema.py`

**Interfaces:**
- Produces: `db.migrate.apply(conn) -> list[str]` (applied file names; also ensures partitions); `db.partitions.add_months(d: date, n: int) -> date`; `ensure_month_partitions(conn, months_ahead=2, today=None) -> list[str]`; `prune_old_partitions(conn, keep_months, today=None) -> list[str]`. CLI: `python -m db.migrate [--test]`, `python -m db.prune [--test] --yes`.

- [ ] **Step 1: Write `db/migrations/001_init.sql`**

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE vessels (
  mmsi            bigint PRIMARY KEY,
  imo             bigint,
  name            text,
  callsign        text,
  flag            text,
  ship_type_code  smallint NOT NULL,
  length_m        real,
  beam_m          real,
  size_class      text NOT NULL DEFAULT 'Unclassified',
  cargo_group     text NOT NULL DEFAULT 'unknown',
  classified_by   text NOT NULL DEFAULT 'dimensions',
  draught_m       real,
  draught_min_m   real,
  draught_max_m   real,
  laden           boolean,
  destination     text,
  eta             timestamptz,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX vessels_name_idx ON vessels (lower(name) text_pattern_ops);
CREATE INDEX vessels_imo_idx ON vessels (imo);

CREATE TABLE positions (
  mmsi       bigint NOT NULL,
  ts         timestamptz NOT NULL,
  geom       geometry(Point, 4326) NOT NULL,
  sog        real,
  cog        real,
  heading    smallint,
  nav_status smallint,
  draught_m  real,
  PRIMARY KEY (mmsi, ts)
) PARTITION BY RANGE (ts);
CREATE TABLE positions_default PARTITION OF positions DEFAULT;
CREATE INDEX positions_geom_idx ON positions USING gist (geom);

CREATE TABLE latest_position (
  mmsi       bigint PRIMARY KEY REFERENCES vessels (mmsi) ON DELETE CASCADE,
  ts         timestamptz NOT NULL,
  geom       geometry(Point, 4326) NOT NULL,
  sog        real,
  cog        real,
  heading    smallint,
  nav_status smallint,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX latest_geom_idx ON latest_position USING gist (geom);
CREATE INDEX latest_updated_idx ON latest_position (updated_at);
```

- [ ] **Step 2: Write `db/partitions.py`**

```python
from __future__ import annotations

import re
from datetime import date

import psycopg


def add_months(d: date, n: int) -> date:
    """First day of the month n months after d's month."""
    idx = d.year * 12 + (d.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _name(start: date) -> str:
    return f"positions_{start:%Y_%m}"


def ensure_month_partitions(conn: psycopg.Connection, months_ahead: int = 2, today: date | None = None) -> list[str]:
    """Create monthly partitions for this month and the next `months_ahead`.

    Must run before rows for that month are inserted: Postgres refuses to create a
    partition whose range already has rows in the DEFAULT partition.
    """
    today = today or date.today()
    names = []
    for i in range(months_ahead + 1):
        start = add_months(today, i)
        end = add_months(start, 1)
        name = _name(start)  # built from dates only, never from user input
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF positions "
            f"FOR VALUES FROM ('{start} 00:00+00') TO ('{end} 00:00+00')"
        )
        names.append(name)
    return names


def prune_old_partitions(conn: psycopg.Connection, keep_months: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    cutoff = add_months(today, -keep_months)
    rows = conn.execute(
        "SELECT c.relname FROM pg_inherits i "
        "JOIN pg_class c ON c.oid = i.inhrelid "
        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'positions'"
    ).fetchall()
    dropped = []
    for row in rows:
        name = row["relname"] if isinstance(row, dict) else row[0]
        m = re.fullmatch(r"positions_(\d{4})_(\d{2})", name)
        if m and date(int(m.group(1)), int(m.group(2)), 1) < cutoff:
            conn.execute(f"DROP TABLE {name}")
            dropped.append(name)
    return sorted(dropped)
```

- [ ] **Step 3: Write `db/migrate.py` and `db/prune.py` and `db/__init__.py` (empty)**

```python
# db/migrate.py
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from common.database import connect
from db.partitions import ensure_month_partitions

MIGRATIONS = Path(__file__).parent / "migrations"


def apply(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name in done:
            continue
        with conn.transaction():
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
        applied.append(f.name)
    ensure_month_partitions(conn)
    return applied


def main() -> None:
    conn = connect(test="--test" in sys.argv)
    applied = apply(conn)
    print("applied:", ", ".join(applied) if applied else "nothing to apply")


if __name__ == "__main__":
    main()
```

```python
# db/prune.py
from __future__ import annotations

import sys

from common.config import load_config
from common.database import connect
from db.partitions import prune_old_partitions


def main() -> None:
    if "--yes" not in sys.argv:
        sys.exit("Refusing to drop partitions without --yes")
    conn = connect(test="--test" in sys.argv)
    dropped = prune_old_partitions(conn, load_config().retention_months)
    print("dropped:", ", ".join(dropped) if dropped else "nothing to drop")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the tests**

```python
# tests/test_partitions.py
from datetime import date

from db.partitions import add_months, ensure_month_partitions, prune_old_partitions


def test_add_months_rolls_over_years():
    assert add_months(date(2026, 11, 20), 2) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 5), -1) == date(2025, 12, 1)


def test_ensure_creates_partitions_and_prune_drops_old_ones(db):
    names = ensure_month_partitions(db, today=date(2020, 1, 15))
    assert names == ["positions_2020_01", "positions_2020_02", "positions_2020_03"]
    assert ensure_month_partitions(db, today=date(2020, 1, 15)) == names  # idempotent
    dropped = prune_old_partitions(db, keep_months=3, today=date(2026, 10, 8))
    assert dropped == names
```

```python
# tests/test_schema.py
def test_tables_exist_and_insert_routes_to_partition(db):
    db.execute(
        "INSERT INTO vessels (mmsi, ship_type_code) VALUES (1, 80)"
    )
    db.execute(
        "INSERT INTO positions (mmsi, ts, geom) VALUES (1, now(), ST_SetSRID(ST_MakePoint(0,0),4326))"
    )
    assert db.execute("SELECT count(*) AS n FROM positions").fetchone()["n"] == 1
```

- [ ] **Step 5: GATE - ask the human to create the databases (do not run these yourself)**

Tell the human to run (psql or shell, as a user allowed to create databases):
```
createdb vessel_tracker
createdb vessel_tracker_test
psql -d vessel_tracker      -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -d vessel_tracker_test -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```
and to set `DATABASE_URL` and `TEST_DATABASE_URL` in their environment *before launching Claude Code* (e.g. `setx DATABASE_URL "postgresql://USER:PASSWORD@localhost:5432/vessel_tracker"`, then restart the session). Wait for confirmation. Do not read or print the values.

- [ ] **Step 6: GATE - ask for explicit confirmation to run the migration against the test database, then run it**

Ask: "OK to run `python -m db.migrate --test` against TEST_DATABASE_URL?" Only after a yes in this session:

Run: `python -m db.migrate --test`
Expected: `applied: 001_init.sql`.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_partitions.py tests/test_schema.py -v`
Expected: PASS (tests needing the DB skip if `TEST_DATABASE_URL` is unset; the human must set it for this task to count as verified).

- [ ] **Step 8: Commit**

```bash
git add db tests
git commit -m "feat: schema, migration runner, month partitions and prune"
```

(The dev database is migrated in Task 6, with its own confirmation.)

---

### Task 4: AIS message models and AISstream parser

**Files:**
- Create: `common/models.py`, `collector/providers/__init__.py`, `collector/providers/aisstream_parse.py`, `tests/samples.py`, `tests/test_parse.py`

**Interfaces:**
- Produces (`common.models`): 
  - `PositionMsg(mmsi:int, ts:datetime, lat:float, lon:float, sog:float|None, cog:float|None, heading:int|None, nav_status:int|None)`
  - `StaticMsg(mmsi:int, ts:datetime, name:str, imo:int|None, callsign:str, ship_type_code:int|None, length_m:float|None, beam_m:float|None, draught_m:float|None, destination:str, eta:datetime|None)`
  - `VesselState(mmsi:int, size_class:str, length_m:float|None, draught_m:float|None, draught_min_m:float|None, draught_max_m:float|None, laden:bool|None)`
  - `AISMessage = PositionMsg | StaticMsg`
- Produces: `collector.providers.aisstream_parse.parse_message(raw: dict) -> AISMessage | None` (pure; no network).

- [ ] **Step 1: Create sample messages `tests/samples.py`**

```python
import copy

POSITION_REPORT = {
    "MessageType": "PositionReport",
    "Metadata": {
        "MMSI": 636012345, "ShipName": "TEST VLCC  ", "latitude": 29.7, "longitude": -93.9,
        "time_utc": "2026-10-08 12:00:00.123456789 +0000 UTC",
    },
    "Message": {"PositionReport": {
        "Cog": 87.4, "Latitude": 29.7, "Longitude": -93.9, "MessageID": 1,
        "NavigationalStatus": 0, "Sog": 12.3, "TrueHeading": 88, "UserID": 636012345, "Valid": True,
    }},
}

SHIP_STATIC_TANKER = {
    "MessageType": "ShipStaticData",
    "Metadata": {"MMSI": 636012345, "ShipName": "TEST VLCC",
                 "time_utc": "2026-10-08 12:00:05.000000000 +0000 UTC"},
    "Message": {"ShipStaticData": {
        "CallSign": "D5XX1  ", "Destination": "HOUSTON      ",
        "Dimension": {"A": 300, "B": 33, "C": 30, "D": 28},
        "Eta": {"Day": 15, "Hour": 6, "Minute": 0, "Month": 10},
        "ImoNumber": 9876543, "MaximumStaticDraught": 19.5,
        "Name": "TEST VLCC   ", "Type": 84, "UserID": 636012345,
    }},
}


def with_position(**overrides):
    m = copy.deepcopy(POSITION_REPORT)
    m["Message"]["PositionReport"].update(overrides)
    return m


def with_static(**overrides):
    m = copy.deepcopy(SHIP_STATIC_TANKER)
    m["Message"]["ShipStaticData"].update(overrides)
    return m
```

- [ ] **Step 2: Write the failing tests `tests/test_parse.py`**

```python
from datetime import datetime, timezone

import pytest

from collector.providers.aisstream_parse import parse_message
from common.models import PositionMsg, StaticMsg
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER, with_position, with_static


def test_position_report_parsed():
    m = parse_message(POSITION_REPORT)
    assert isinstance(m, PositionMsg)
    assert (m.mmsi, m.lat, m.lon, m.sog, m.cog, m.heading, m.nav_status) == (
        636012345, 29.7, -93.9, 12.3, 87.4, 88, 0)
    # nanosecond fraction is truncated to microseconds
    assert m.ts == datetime(2026, 10, 8, 12, 0, 0, 123456, tzinfo=timezone.utc)


@pytest.mark.parametrize(  # Review Focus 3
    "overrides,field",
    [({"Sog": 102.3}, "sog"), ({"Cog": 360}, "cog"), ({"TrueHeading": 511}, "heading")],
)
def test_not_available_values_become_none(overrides, field):
    m = parse_message(with_position(**overrides))
    assert getattr(m, field) is None


@pytest.mark.parametrize(
    "overrides",
    [{"Latitude": 91.0}, {"Longitude": 181.0}, {"Latitude": 0.0, "Longitude": 0.0}],
)
def test_invalid_positions_dropped(overrides):  # Review Focus 3
    assert parse_message(with_position(**overrides)) is None


def test_static_parsed():
    m = parse_message(SHIP_STATIC_TANKER)
    assert isinstance(m, StaticMsg)
    assert m.mmsi == 636012345 and m.imo == 9876543 and m.ship_type_code == 84
    assert m.name == "TEST VLCC" and m.callsign == "D5XX1" and m.destination == "HOUSTON"
    assert m.length_m == 333 and m.beam_m == 58 and m.draught_m == 19.5
    assert m.eta == datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)


def test_zero_dimensions_and_draught_become_none():  # Review Focus 3
    m = parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0}, MaximumStaticDraught=0))
    assert m.length_m is None and m.beam_m is None and m.draught_m is None


@pytest.mark.parametrize("eta", [{"Month": 0, "Day": 0, "Hour": 24, "Minute": 60},
                                 {"Month": 2, "Day": 31, "Hour": 1, "Minute": 1}])
def test_unavailable_or_impossible_eta_is_none(eta):  # Review Focus 3
    assert parse_message(with_static(Eta=eta)).eta is None


def test_eta_in_the_past_rolls_to_next_year():
    m = parse_message(with_static(Eta={"Month": 1, "Day": 5, "Hour": 0, "Minute": 0}))
    assert m.eta == datetime(2027, 1, 5, 0, 0, tzinfo=timezone.utc)


def test_empty_name_is_empty_string_not_crash():
    m = parse_message(with_static(Name="", Destination="", CallSign=""))
    assert (m.name, m.destination, m.callsign) == ("", "", "")


@pytest.mark.parametrize("raw", [{}, {"MessageType": "Other"}, {"MessageType": "PositionReport"},
                                 {"MessageType": "ShipStaticData", "Message": {}}, {"error": "x"}])
def test_unknown_or_malformed_returns_none(raw):
    assert parse_message(raw) is None
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_parse.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement `common/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PositionMsg:
    mmsi: int
    ts: datetime
    lat: float
    lon: float
    sog: float | None
    cog: float | None
    heading: int | None
    nav_status: int | None


@dataclass(frozen=True)
class StaticMsg:
    mmsi: int
    ts: datetime
    name: str
    imo: int | None
    callsign: str
    ship_type_code: int | None
    length_m: float | None
    beam_m: float | None
    draught_m: float | None
    destination: str
    eta: datetime | None


@dataclass(frozen=True)
class VesselState:
    mmsi: int
    size_class: str
    length_m: float | None
    draught_m: float | None
    draught_min_m: float | None
    draught_max_m: float | None
    laden: bool | None


AISMessage = PositionMsg | StaticMsg
```

- [ ] **Step 5: Implement `collector/providers/__init__.py` (empty) and `collector/providers/aisstream_parse.py`**

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from common.models import AISMessage, PositionMsg, StaticMsg


def parse_message(raw: dict) -> AISMessage | None:
    """Normalize one decoded AISstream message. Returns None for anything unusable."""
    try:
        mtype = raw.get("MessageType")
        if mtype == "PositionReport":
            return _position(raw)
        if mtype == "ShipStaticData":
            return _static(raw)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return None


def _parse_ts(s: str) -> datetime:
    date_part, time_part = s.split()[:2]
    fmt = "%Y-%m-%d %H:%M:%S"
    if "." in time_part:
        whole, frac = time_part.split(".")
        time_part = f"{whole}.{frac[:6]}"
        fmt += ".%f"
    return datetime.strptime(f"{date_part} {time_part}", fmt).replace(tzinfo=timezone.utc)


def _position(raw: dict) -> PositionMsg | None:
    p = raw["Message"]["PositionReport"]
    ts = _parse_ts(raw["Metadata"]["time_utc"])
    lat, lon = float(p["Latitude"]), float(p["Longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    sog = p.get("Sog")
    cog = p.get("Cog")
    heading = p.get("TrueHeading")
    nav = p.get("NavigationalStatus")
    return PositionMsg(
        mmsi=int(p["UserID"]),
        ts=ts,
        lat=lat,
        lon=lon,
        sog=None if sog is None or sog >= 102.3 else float(sog),
        cog=None if cog is None or cog >= 360 else float(cog),
        heading=None if heading is None or not 0 <= heading < 360 else int(heading),
        nav_status=None if nav is None else int(nav),
    )


def _static(raw: dict) -> StaticMsg:
    s = raw["Message"]["ShipStaticData"]
    ts = _parse_ts(raw["Metadata"]["time_utc"])
    dim = s.get("Dimension") or {}
    length = (dim.get("A") or 0) + (dim.get("B") or 0)
    beam = (dim.get("C") or 0) + (dim.get("D") or 0)
    draught = s.get("MaximumStaticDraught") or 0
    imo = s.get("ImoNumber") or None
    return StaticMsg(
        mmsi=int(s["UserID"]),
        ts=ts,
        name=(s.get("Name") or "").strip(),
        imo=int(imo) if imo else None,
        callsign=(s.get("CallSign") or "").strip(),
        ship_type_code=s.get("Type"),
        length_m=float(length) if length > 0 else None,
        beam_m=float(beam) if beam > 0 else None,
        draught_m=float(draught) if draught > 0 else None,
        destination=(s.get("Destination") or "").strip(),
        eta=_eta(s.get("Eta") or {}, ts),
    )


def _eta(e: dict, ts: datetime) -> datetime | None:
    month, day = e.get("Month", 0), e.get("Day", 0)
    hour, minute = e.get("Hour", 24), e.get("Minute", 60)
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour < 24 and 0 <= minute < 60):
        return None
    try:
        eta = datetime(ts.year, month, day, hour, minute, tzinfo=timezone.utc)
        if eta < ts - timedelta(days=30):
            eta = eta.replace(year=ts.year + 1)
    except ValueError:
        return None
    return eta
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_parse.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add common collector tests
git commit -m "feat: AIS message models and AISstream parser"
```

---

### Task 5: Provider interface and AISstream websocket provider

**Files:**
- Create: `collector/providers/base.py`, `collector/providers/aisstream.py`, `tests/test_provider.py`

**Interfaces:**
- Consumes: `parse_message`.
- Produces: `collector.providers.base.AISProvider` (Protocol with `def messages(self) -> AsyncIterator[AISMessage]`); `collector.providers.aisstream.AISStreamProvider(api_key: str | None = None, url: str = URL, initial_delay: float = 1.0)` with `.dropped: int` and `async messages()` that connects, subscribes, yields normalized messages, and reconnects with backoff.

- [ ] **Step 1: Create `collector/providers/base.py`**

```python
from __future__ import annotations

from typing import AsyncIterator, Protocol

from common.models import AISMessage


class AISProvider(Protocol):
    """A source of normalized AIS messages. Swap implementations to change data feed."""

    def messages(self) -> AsyncIterator[AISMessage]: ...
```

- [ ] **Step 2: Write the failing test `tests/test_provider.py`**

The test runs against a **local** websocket server on 127.0.0.1; it makes no external connection.

```python
import asyncio
import json

from websockets.asyncio.server import serve

from collector.providers.aisstream import AISStreamProvider
from common.models import PositionMsg, StaticMsg
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER


async def test_subscribes_parses_ignores_errors_and_reconnects():
    subscriptions = []
    connections = 0

    async def handler(ws):
        nonlocal connections
        connections += 1
        subscriptions.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"error": "something"}))      # must be skipped, not crash
        await ws.send("not json")                              # must be skipped, not crash
        if connections == 1:
            await ws.send(json.dumps(SHIP_STATIC_TANKER))
            await ws.close()                                   # force a reconnect
        else:
            await ws.send(json.dumps(POSITION_REPORT))
            await asyncio.sleep(5)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = AISStreamProvider(api_key="fake-test-key", url=f"ws://127.0.0.1:{port}", initial_delay=0.01)
        got = []
        async with asyncio.timeout(10):
            gen = provider.messages()
            async for msg in gen:
                got.append(msg)
                if len(got) == 2:
                    break
            await gen.aclose()

    assert isinstance(got[0], StaticMsg) and isinstance(got[1], PositionMsg)
    assert connections == 2
    sub = subscriptions[0]
    assert sub["APIKey"] == "fake-test-key"
    assert sub["BoundingBoxes"] == [[[-90, -180], [90, 180]]]
    assert sorted(sub["FilterMessageTypes"]) == ["PositionReport", "ShipStaticData"]
    assert provider.dropped >= 2


def test_missing_api_key_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("AISSTREAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AISSTREAM_API_KEY"):
        AISStreamProvider()
```

- [ ] **Step 3: GATE - confirm before writing network code**

Ask the human: "`collector/providers/aisstream.py` will connect to the external service `wss://stream.aisstream.io/v0/stream` using the `AISSTREAM_API_KEY` environment variable. OK to write it?" Proceed only after a yes in this session. (Tests use a local server only.)

- [ ] **Step 4: Run to verify failure**

Run: `python -m pytest tests/test_provider.py -v`
Expected: FAIL (`ModuleNotFoundError: collector.providers.aisstream`).

- [ ] **Step 5: Implement `collector/providers/aisstream.py`**

```python
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import AsyncIterator

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from collector.providers.aisstream_parse import parse_message
from common.models import AISMessage

URL = "wss://stream.aisstream.io/v0/stream"
log = logging.getLogger(__name__)


class AISStreamProvider:
    def __init__(self, api_key: str | None = None, url: str = URL, initial_delay: float = 1.0):
        key = api_key or os.environ.get("AISSTREAM_API_KEY")
        if not key:
            raise RuntimeError("AISSTREAM_API_KEY environment variable is not set")
        self._key = key
        self.url = url
        self.initial_delay = initial_delay
        self.dropped = 0

    def _subscription(self) -> dict:
        return {
            "APIKey": self._key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

    async def messages(self) -> AsyncIterator[AISMessage]:
        delay = self.initial_delay
        while True:
            try:
                async with connect(self.url, ping_interval=20) as ws:
                    await ws.send(json.dumps(self._subscription()))
                    delay = self.initial_delay
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except (ValueError, TypeError):
                            self.dropped += 1
                            continue
                        if isinstance(data, dict) and "error" in data:
                            log.error("AISstream error message: %s", data["error"])
                            self.dropped += 1
                            continue
                        msg = parse_message(data) if isinstance(data, dict) else None
                        if msg is None:
                            self.dropped += 1
                            continue
                        yield msg
            except (WebSocketException, OSError) as exc:
                log.warning("AISstream connection lost (%s); reconnecting", type(exc).__name__)
            await asyncio.sleep(delay + random.random() * delay)
            delay = min(delay * 2, 60.0)
```

- [ ] **Step 6: Run to verify pass**

Run: `python -m pytest tests/test_provider.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add collector tests
git commit -m "feat: AISProvider interface and AISstream websocket provider"
```

---

### Task 6: Store, pipeline and collector main

**Files:**
- Create: `collector/store.py`, `collector/pipeline.py`, `collector/main.py`, `tests/test_pipeline.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `classify`, `estimate_laden`, `is_tanker_type`, `flag_from_mmsi`, models, `Config`.
- Produces:
  - `Store(conn).upsert_vessel(msg: StaticMsg, cls: Classification, state: VesselState) -> None`
  - `Store.add_position(msg: PositionMsg, draught_m: float | None) -> None`
  - `Store.load_tanker_states() -> dict[int, VesselState]`
  - `Pipeline(store, cfg, tankers: dict[int, VesselState] | None = None)` with `.handle(msg: AISMessage) -> None`, `.counters: dict[str, int]` (keys `tanker_static`, `non_tanker_static`, `position_stored`, `position_unknown`).
  - CLI: `python -m collector.main`.

- [ ] **Step 1: Write the failing pipeline tests (fake store, no DB)**

```python
# tests/test_pipeline.py
from collector.pipeline import Pipeline
from common.config import load_config
from tests.samples import POSITION_REPORT, SHIP_STATIC_TANKER, with_static
from collector.providers.aisstream_parse import parse_message

CFG = load_config()


class FakeStore:
    def __init__(self):
        self.vessels, self.positions = [], []

    def upsert_vessel(self, msg, cls, state):
        self.vessels.append((msg, cls, state))

    def add_position(self, msg, draught_m):
        self.positions.append((msg, draught_m))


def make():
    store = FakeStore()
    return store, Pipeline(store, CFG)


def test_position_before_static_is_dropped():  # Review Focus 1
    store, p = make()
    p.handle(parse_message(POSITION_REPORT))
    assert store.positions == [] and p.counters["position_unknown"] == 1


def test_non_tanker_static_then_position_is_dropped():  # Review Focus 1
    store, p = make()
    p.handle(parse_message(with_static(Type=70)))
    p.handle(parse_message(POSITION_REPORT))
    assert store.vessels == [] and store.positions == []
    assert p.counters["non_tanker_static"] == 1


def test_tanker_static_then_position_is_stored_with_draught():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    (_, cls, state), = store.vessels
    assert cls.size_class == "ULCC/VLCC" and state.draught_m == 19.5 and state.laden is True
    p.handle(parse_message(POSITION_REPORT))
    (pos, draught), = store.positions
    assert pos.mmsi == 636012345 and draught == 19.5


def test_later_static_updates_draught_range_and_laden():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))                      # 19.5 m
    p.handle(parse_message(with_static(MaximumStaticDraught=9.0)))   # ballast now
    state = store.vessels[-1][2]
    assert (state.draught_min_m, state.draught_max_m) == (9.0, 19.5)
    assert state.laden is False


def test_static_without_dimensions_keeps_previous_length():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    p.handle(parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0})))
    assert store.vessels[-1][1].size_class == "ULCC/VLCC"


def test_tanker_without_dimensions_is_unclassified():  # Review Focus 3
    store, p = make()
    p.handle(parse_message(with_static(Dimension={"A": 0, "B": 0, "C": 0, "D": 0})))
    assert store.vessels[0][1].size_class == "Unclassified"


def test_type_change_to_non_tanker_forgets_vessel():
    store, p = make()
    p.handle(parse_message(SHIP_STATIC_TANKER))
    p.handle(parse_message(with_static(Type=70)))
    p.handle(parse_message(POSITION_REPORT))
    assert store.positions == []
```

- [ ] **Step 2: Write the failing store tests (test DB)**

```python
# tests/test_store.py
from datetime import datetime, timedelta, timezone

from collector.classify import Classification
from collector.providers.aisstream_parse import parse_message
from collector.store import Store
from common.models import PositionMsg, VesselState
from tests.samples import SHIP_STATIC_TANKER

STATE = VesselState(636012345, "ULCC/VLCC", 333.0, 19.5, 19.5, 19.5, True)
CLS = Classification("ULCC/VLCC", "crude")
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def pos(ts, lon=-93.9):
    return PositionMsg(636012345, ts, 29.7, lon, 12.3, 87.4, 88, 0)


def test_upsert_vessel_and_reload_state(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    row = db.execute("SELECT name, flag, size_class, imo, laden FROM vessels WHERE mmsi = 636012345").fetchone()
    assert tuple(row.values()) == ("TEST VLCC", "Liberia", "ULCC/VLCC", 9876543, True)
    assert store.load_tanker_states()[636012345] == STATE


def test_empty_name_does_not_overwrite_existing(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    blank = parse_message({**SHIP_STATIC_TANKER, "Message": {"ShipStaticData": {
        **SHIP_STATIC_TANKER["Message"]["ShipStaticData"], "Name": ""}}})
    store.upsert_vessel(blank, CLS, STATE)
    assert db.execute("SELECT name FROM vessels").fetchone()["name"] == "TEST VLCC"


def test_positions_stored_and_latest_only_moves_forward(db):
    store = Store(db)
    store.upsert_vessel(parse_message(SHIP_STATIC_TANKER), CLS, STATE)
    store.add_position(pos(T0 + timedelta(minutes=5), lon=-90.0), 19.5)
    store.add_position(pos(T0, lon=-95.0), 19.5)                    # older: history only
    store.add_position(pos(T0, lon=-95.0), 19.5)                    # duplicate (mmsi, ts): ignored
    assert db.execute("SELECT count(*) AS n FROM positions").fetchone()["n"] == 2
    lon = db.execute("SELECT ST_X(geom) AS lon FROM latest_position").fetchone()["lon"]
    assert lon == -90.0
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_pipeline.py tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError: collector.pipeline`).

- [ ] **Step 4: Implement `collector/pipeline.py`**

```python
from __future__ import annotations

from typing import Protocol

from collector.classify import Classification, classify, estimate_laden, is_tanker_type
from common.config import Config
from common.models import AISMessage, PositionMsg, StaticMsg, VesselState


class StoreLike(Protocol):
    def upsert_vessel(self, msg: StaticMsg, cls: Classification, state: VesselState) -> None: ...
    def add_position(self, msg: PositionMsg, draught_m: float | None) -> None: ...


class Pipeline:
    """Keeps only tankers. A vessel becomes known when a tanker static message arrives."""

    def __init__(self, store: StoreLike, cfg: Config, tankers: dict[int, VesselState] | None = None):
        self.store = store
        self.cfg = cfg
        self.tankers: dict[int, VesselState] = dict(tankers or {})
        self.counters = {"tanker_static": 0, "non_tanker_static": 0, "position_stored": 0, "position_unknown": 0}

    def handle(self, msg: AISMessage) -> None:
        if isinstance(msg, StaticMsg):
            self._static(msg)
        else:
            self._position(msg)

    def _static(self, msg: StaticMsg) -> None:
        if not is_tanker_type(msg.ship_type_code):
            self.tankers.pop(msg.mmsi, None)
            self.counters["non_tanker_static"] += 1
            return
        prev = self.tankers.get(msg.mmsi)
        length = msg.length_m or (prev.length_m if prev else None)
        draught = msg.draught_m or (prev.draught_m if prev else None)
        dmin = prev.draught_min_m if prev else None
        dmax = prev.draught_max_m if prev else None
        if msg.draught_m:
            dmin = msg.draught_m if dmin is None else min(dmin, msg.draught_m)
            dmax = msg.draught_m if dmax is None else max(dmax, msg.draught_m)
        cls = classify(length, self.cfg)
        state = VesselState(
            mmsi=msg.mmsi,
            size_class=cls.size_class,
            length_m=length,
            draught_m=draught,
            draught_min_m=dmin,
            draught_max_m=dmax,
            laden=estimate_laden(cls.size_class, draught, dmin, dmax, self.cfg),
        )
        self.tankers[msg.mmsi] = state
        self.store.upsert_vessel(msg, cls, state)
        self.counters["tanker_static"] += 1

    def _position(self, msg: PositionMsg) -> None:
        state = self.tankers.get(msg.mmsi)
        if state is None:
            self.counters["position_unknown"] += 1
            return
        self.store.add_position(msg, state.draught_m)
        self.counters["position_stored"] += 1
```

- [ ] **Step 5: Implement `collector/store.py`**

```python
from __future__ import annotations

import psycopg

from collector.classify import Classification
from common.flags import flag_from_mmsi
from common.models import PositionMsg, StaticMsg, VesselState


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def upsert_vessel(self, msg: StaticMsg, cls: Classification, state: VesselState) -> None:
        self.conn.execute(
            """
            INSERT INTO vessels (mmsi, imo, name, callsign, flag, ship_type_code, length_m, beam_m,
                size_class, cargo_group, draught_m, draught_min_m, draught_max_m, laden,
                destination, eta, updated_at)
            VALUES (%(mmsi)s, %(imo)s, %(name)s, %(callsign)s, %(flag)s, %(type)s, %(length)s, %(beam)s,
                %(size_class)s, %(cargo_group)s, %(draught)s, %(dmin)s, %(dmax)s, %(laden)s,
                %(dest)s, %(eta)s, now())
            ON CONFLICT (mmsi) DO UPDATE SET
                imo = COALESCE(EXCLUDED.imo, vessels.imo),
                name = COALESCE(NULLIF(EXCLUDED.name, ''), vessels.name),
                callsign = COALESCE(NULLIF(EXCLUDED.callsign, ''), vessels.callsign),
                ship_type_code = EXCLUDED.ship_type_code,
                length_m = COALESCE(EXCLUDED.length_m, vessels.length_m),
                beam_m = COALESCE(EXCLUDED.beam_m, vessels.beam_m),
                size_class = EXCLUDED.size_class, cargo_group = EXCLUDED.cargo_group,
                draught_m = EXCLUDED.draught_m, draught_min_m = EXCLUDED.draught_min_m,
                draught_max_m = EXCLUDED.draught_max_m, laden = EXCLUDED.laden,
                destination = COALESCE(NULLIF(EXCLUDED.destination, ''), vessels.destination),
                eta = EXCLUDED.eta, updated_at = now()
            """,
            {
                "mmsi": msg.mmsi, "imo": msg.imo, "name": msg.name, "callsign": msg.callsign,
                "flag": flag_from_mmsi(msg.mmsi), "type": msg.ship_type_code,
                "length": msg.length_m, "beam": msg.beam_m,
                "size_class": cls.size_class, "cargo_group": cls.cargo_group,
                "draught": state.draught_m, "dmin": state.draught_min_m, "dmax": state.draught_max_m,
                "laden": state.laden, "dest": msg.destination, "eta": msg.eta,
            },
        )

    def add_position(self, msg: PositionMsg, draught_m: float | None) -> None:
        params = {
            "mmsi": msg.mmsi, "ts": msg.ts, "lon": msg.lon, "lat": msg.lat, "sog": msg.sog,
            "cog": msg.cog, "heading": msg.heading, "nav": msg.nav_status, "draught": draught_m,
        }
        self.conn.execute(
            """
            INSERT INTO positions (mmsi, ts, geom, sog, cog, heading, nav_status, draught_m)
            VALUES (%(mmsi)s, %(ts)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                    %(sog)s, %(cog)s, %(heading)s, %(nav)s, %(draught)s)
            ON CONFLICT (mmsi, ts) DO NOTHING
            """,
            params,
        )
        self.conn.execute(
            """
            INSERT INTO latest_position (mmsi, ts, geom, sog, cog, heading, nav_status, updated_at)
            VALUES (%(mmsi)s, %(ts)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                    %(sog)s, %(cog)s, %(heading)s, %(nav)s, now())
            ON CONFLICT (mmsi) DO UPDATE SET
                ts = EXCLUDED.ts, geom = EXCLUDED.geom, sog = EXCLUDED.sog, cog = EXCLUDED.cog,
                heading = EXCLUDED.heading, nav_status = EXCLUDED.nav_status, updated_at = now()
            WHERE latest_position.ts < EXCLUDED.ts
            """,
            params,
        )

    def load_tanker_states(self) -> dict[int, VesselState]:
        rows = self.conn.execute(
            "SELECT mmsi, size_class, length_m, draught_m, draught_min_m, draught_max_m, laden FROM vessels"
        ).fetchall()
        return {r[0]: VesselState(*r) for r in rows}
```

- [ ] **Step 6: Implement `collector/main.py`**

```python
from __future__ import annotations

import asyncio
import logging
import time

import psycopg

from collector.pipeline import Pipeline
from collector.providers.aisstream import AISStreamProvider
from collector.store import Store
from common.config import load_config
from common.database import connect
from db.partitions import ensure_month_partitions

log = logging.getLogger("collector")


async def run() -> None:
    cfg = load_config()
    store = Store(connect())
    ensure_month_partitions(store.conn)
    pipeline = Pipeline(store, cfg, store.load_tanker_states())
    provider = AISStreamProvider()
    last_partition_check = last_report = time.monotonic()
    async for msg in provider.messages():
        try:
            pipeline.handle(msg)
        except psycopg.OperationalError:
            log.exception("database connection lost; reconnecting in 5 s")
            await asyncio.sleep(5)
            store.conn = connect()
        now = time.monotonic()
        if now - last_partition_check > 3600:
            ensure_month_partitions(store.conn)
            last_partition_check = now
        if now - last_report > 60:
            log.info("known_tankers=%d dropped=%d %s", len(pipeline.tankers), provider.dropped, pipeline.counters)
            last_report = now


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run to verify pass**

Run: `python -m pytest tests/test_pipeline.py tests/test_store.py -v`
Expected: all PASS.

- [ ] **Step 8: GATE - migrate the dev database, then smoke-test the live feed**

Ask: "OK to run `python -m db.migrate` against DATABASE_URL (the dev database)?" After a yes:
Run: `python -m db.migrate` -> expect `applied: 001_init.sql`.

Then ask the human to confirm `AISSTREAM_API_KEY` is set in the environment and run the collector for about 2 minutes:
Run (background): `python -m collector.main`
Expected log line within ~60 s such as `known_tankers=... tanker_static=...>0`. Then verify with:
`python -c "from common.database import connect; c=connect(); print(c.execute('select count(*) from vessels').fetchone(), c.execute('select count(*) from latest_position').fetchone())"`
Expected: both counts > 0 after a few minutes. Stop the collector. Never print the key.

- [ ] **Step 9: Commit**

```bash
git add collector tests
git commit -m "feat: collector pipeline, store and entrypoint"
```

---

### Task 7: API filters and queries

**Files:**
- Create: `api/__init__.py`, `api/filters.py`, `api/queries.py`, `tests/helpers.py`, `tests/test_filters.py`, `tests/test_queries.py`

**Interfaces:**
- Consumes: `Config`, DB schema.
- Produces:
  - `api.filters.VesselFilters(bbox=None, size_class=(), cargo_group=(), laden=None, flag=(), nav_status=(), min_speed=None, max_speed=None)` (frozen dataclass); `build_where(f, stale_hours, skip: str | None = None) -> tuple[str, list]`; `filters_from_json(d: dict) -> VesselFilters`.
  - `api.queries`: `list_vessels(conn, f, zoom, cfg) -> dict` (FeatureCollection), `vessel_detail(conn, mmsi) -> dict | None`, `vessel_track(conn, mmsi, start, end) -> dict`, `search(conn, q, limit=20) -> list[dict]`, `stats(conn, f, cfg) -> dict`, `meta(cfg) -> dict`, `updated_since(conn, f, since, cfg, limit=2000) -> tuple[list[dict], datetime]`, `split_antimeridian(coords) -> list[list]`, `downsample(items, max_points) -> list`. Constants `CLUSTER_ZOOM = 5`.
  - Test helper `tests.helpers.seed_vessel(conn, mmsi, *, name="TEST", size_class="MR", cargo_group="products", laden=None, flag="Panama", imo=None, lon=0.0, lat=0.0, age_hours=0.0, sog=10.0, cog=90.0, nav_status=0)`.

- [ ] **Step 1: Create `tests/helpers.py`**

```python
def seed_vessel(conn, mmsi, *, name="TEST", size_class="MR", cargo_group="products", laden=None,
                flag="Panama", imo=None, lon=0.0, lat=0.0, age_hours=0.0, sog=10.0, cog=90.0, nav_status=0):
    conn.execute(
        "INSERT INTO vessels (mmsi, imo, name, flag, ship_type_code, size_class, cargo_group, laden) "
        "VALUES (%s, %s, %s, %s, 80, %s, %s, %s)",
        (mmsi, imo, name, flag, size_class, cargo_group, laden),
    )
    conn.execute(
        "INSERT INTO latest_position (mmsi, ts, geom, sog, cog, heading, nav_status) "
        "VALUES (%s, now() - %s::float8 * interval '1 hour', ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, 90, %s)",
        (mmsi, age_hours, lon, lat, sog, cog, nav_status),
    )
```

- [ ] **Step 2: Write failing filter tests (no DB) `tests/test_filters.py`**

```python
from api.filters import VesselFilters, build_where, filters_from_json


def test_default_filters_only_apply_stale_cutoff():
    where, params = build_where(VesselFilters(), stale_hours=6)
    assert "lp.ts >" in where and params == [6]


def test_all_filters_produce_clauses_and_params():
    f = VesselFilters(bbox=(0, 1, 2, 3), size_class=("MR",), cargo_group=("products",), laden=True,
                      flag=("Panama",), nav_status=(0, 1), min_speed=1.0, max_speed=5.0)
    where, params = build_where(f, 6)
    assert where.count("%s") == len(params)
    assert ["MR"] in params and [0, 1] in params and True in params


def test_antimeridian_bbox_uses_two_envelopes():  # Review Focus 2
    where, params = build_where(VesselFilters(bbox=(170.0, -10.0, -170.0, 10.0)), 6)
    assert where.count("ST_MakeEnvelope") == 2
    assert 170.0 in params and -170.0 in params and 180 in params and -180 in params


def test_normal_bbox_uses_one_envelope():
    where, _ = build_where(VesselFilters(bbox=(-10.0, -10.0, 10.0, 10.0)), 6)
    assert where.count("ST_MakeEnvelope") == 1


def test_skip_omits_one_dimension():
    f = VesselFilters(size_class=("MR",), cargo_group=("products",))
    where, params = build_where(f, 6, skip="size_class")
    assert "size_class" not in where and ["products"] in params and ["MR"] not in params


def test_filters_from_json_roundtrip_and_garbage():
    f = filters_from_json({"bbox": [1, 2, 3, 4], "size_class": ["MR"], "laden": False, "nav_status": ["0"]})
    assert f.bbox == (1.0, 2.0, 3.0, 4.0) and f.size_class == ("MR",) and f.laden is False and f.nav_status == (0,)
    assert filters_from_json({"bbox": [1, 2]}).bbox is None          # wrong length ignored
    assert filters_from_json({"nav_status": ["x"]}) == VesselFilters()  # unparseable -> defaults
```

- [ ] **Step 3: Implement `api/__init__.py` (empty) and `api/filters.py`**

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VesselFilters:
    bbox: tuple[float, float, float, float] | None = None  # west, south, east, north
    size_class: tuple[str, ...] = ()
    cargo_group: tuple[str, ...] = ()
    laden: bool | None = None
    flag: tuple[str, ...] = ()
    nav_status: tuple[int, ...] = ()
    min_speed: float | None = None
    max_speed: float | None = None


def build_where(f: VesselFilters, stale_hours: float, skip: str | None = None) -> tuple[str, list]:
    """WHERE clause over `latest_position lp JOIN vessels v`. `skip` omits one filter dimension (for facet counts)."""
    clauses = ["lp.ts > now() - %s::float8 * interval '1 hour'"]
    params: list = [stale_hours]
    if f.bbox is not None and skip != "bbox":
        w, s, e, n = f.bbox
        if w > e:  # view crosses the antimeridian
            clauses.append(
                "(lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326) OR lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            params += [w, s, 180, n, -180, s, e, n]
        else:
            clauses.append("lp.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
            params += [w, s, e, n]
    if f.size_class and skip != "size_class":
        clauses.append("v.size_class = ANY(%s)")
        params.append(list(f.size_class))
    if f.cargo_group and skip != "cargo_group":
        clauses.append("v.cargo_group = ANY(%s)")
        params.append(list(f.cargo_group))
    if f.laden is not None and skip != "laden":
        clauses.append("v.laden = %s")
        params.append(f.laden)
    if f.flag and skip != "flag":
        clauses.append("v.flag = ANY(%s)")
        params.append(list(f.flag))
    if f.nav_status and skip != "nav_status":
        clauses.append("lp.nav_status = ANY(%s)")
        params.append(list(f.nav_status))
    if f.min_speed is not None:
        clauses.append("lp.sog >= %s")
        params.append(f.min_speed)
    if f.max_speed is not None:
        clauses.append("lp.sog <= %s")
        params.append(f.max_speed)
    return " AND ".join(clauses), params


def filters_from_json(d: dict) -> VesselFilters:
    """Build filters from a websocket subscription message. Garbage yields defaults."""
    try:
        bbox = d.get("bbox")
        bbox = tuple(float(x) for x in bbox) if bbox is not None else None
        if bbox is not None and len(bbox) != 4:
            bbox = None
        return VesselFilters(
            bbox=bbox,
            size_class=tuple(d.get("size_class") or ()),
            cargo_group=tuple(d.get("cargo_group") or ()),
            laden=d.get("laden"),
            flag=tuple(d.get("flag") or ()),
            nav_status=tuple(int(x) for x in (d.get("nav_status") or ())),
            min_speed=None if d.get("min_speed") is None else float(d["min_speed"]),
            max_speed=None if d.get("max_speed") is None else float(d["max_speed"]),
        )
    except (TypeError, ValueError):
        return VesselFilters()
```

- [ ] **Step 4: Run filter tests**

Run: `python -m pytest tests/test_filters.py -v`
Expected: PASS.

- [ ] **Step 5: Write failing query tests `tests/test_queries.py`**

```python
from datetime import datetime, timedelta, timezone

from api import queries
from api.filters import VesselFilters
from common.config import load_config
from tests.helpers import seed_vessel

CFG = load_config()


def ids(fc):
    return sorted(f["properties"]["mmsi"] for f in fc["features"])


def test_list_filters_by_class_laden_and_hides_stale(db):  # Review Focus 4
    seed_vessel(db, 1, size_class="MR", laden=True, lon=10, lat=10)
    seed_vessel(db, 2, size_class="Suezmax", laden=False, lon=11, lat=11)
    seed_vessel(db, 3, size_class="MR", laden=True, lon=12, lat=12, age_hours=7)     # stale
    assert ids(queries.list_vessels(db, VesselFilters(), 8, CFG)) == [1, 2]
    assert ids(queries.list_vessels(db, VesselFilters(size_class=("MR",)), 8, CFG)) == [1]
    assert ids(queries.list_vessels(db, VesselFilters(laden=False), 8, CFG)) == [2]


def test_bbox_including_antimeridian(db):  # Review Focus 2
    seed_vessel(db, 1, lon=175, lat=0)
    seed_vessel(db, 2, lon=-175, lat=0)
    seed_vessel(db, 3, lon=0, lat=0)
    fc = queries.list_vessels(db, VesselFilters(bbox=(170, -10, -170, 10)), 8, CFG)
    assert ids(fc) == [1, 2]


def test_zoomed_out_returns_clusters(db):
    for i in range(5):
        seed_vessel(db, 10 + i, lon=10.0 + i * 0.01, lat=10.0)
    fc = queries.list_vessels(db, VesselFilters(), 2, CFG)
    assert len(fc["features"]) == 1
    assert fc["features"][0]["properties"] == {"cluster": True, "count": 5}


def test_detail_and_404_shape(db):
    seed_vessel(db, 1, name="ALPHA", imo=1234567, lon=1, lat=2)
    d = queries.vessel_detail(db, 1)
    assert d["name"] == "ALPHA" and d["position"]["lon"] == 1 and d["inferred"] == {"cargo_group": True, "laden": True}
    assert queries.vessel_detail(db, 999) is None


def test_stale_vessel_detail_and_track_still_available(db):  # Review Focus 4
    seed_vessel(db, 1, age_hours=48)
    now = datetime.now(timezone.utc)
    db.execute("INSERT INTO positions (mmsi, ts, geom) VALUES (1, %s, ST_SetSRID(ST_MakePoint(1,1),4326)), "
               "(1, %s, ST_SetSRID(ST_MakePoint(2,1),4326))", (now - timedelta(hours=49), now - timedelta(hours=48)))
    assert queries.vessel_detail(db, 1) is not None
    tr = queries.vessel_track(db, 1, now - timedelta(days=3), now)
    assert tr["properties"]["point_count"] == 2


def test_stats_are_faceted(db):
    seed_vessel(db, 1, size_class="MR", cargo_group="products", laden=True)
    seed_vessel(db, 2, size_class="MR", cargo_group="products", laden=False)
    seed_vessel(db, 3, size_class="Suezmax", cargo_group="mostly_crude", laden=True)
    s = queries.stats(db, VesselFilters(size_class=("MR",)), CFG)
    assert s["total"] == 2
    assert s["size_class"] == {"MR": 2, "Suezmax": 1}      # own dimension ignores its own filter
    assert s["laden"] == {"laden": 1, "ballast": 1}        # other dimensions respect it
    assert s["newest_ts"] is not None


def test_search(db):  # Review Focus 5
    seed_vessel(db, 111111111, name="NORDIC MARS", imo=9000001)
    seed_vessel(db, 222222222, name="100% STAR_X")
    assert [r["mmsi"] for r in queries.search(db, "mars")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "9000001")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "111111111")] == [111111111]
    assert [r["mmsi"] for r in queries.search(db, "100%")] == [222222222]   # wildcard is literal
    assert queries.search(db, "%%") == []                                      # not a match-all
    assert queries.search(db, "a") == [] and queries.search(db, "") == []
    assert queries.search(db, "9" * 40) == []                                  # absurd digit string


def test_updated_since_returns_only_newer(db):
    seed_vessel(db, 1, lon=1, lat=1)
    t0 = datetime.now(timezone.utc)
    assert queries.updated_since(db, VesselFilters(), t0, CFG)[0] == []
    db.execute("UPDATE latest_position SET updated_at = now()")
    feats, newest = queries.updated_since(db, VesselFilters(), t0, CFG)
    assert [f["properties"]["mmsi"] for f in feats] == [1] and newest > t0


def test_split_antimeridian_and_downsample():  # Review Focus 2
    lines = queries.split_antimeridian([[170, 0], [179, 0], [-179, 0], [-170, 0]])
    assert lines == [[[170, 0], [179, 0]], [[-179, 0], [-170, 0]]]
    pts = list(range(5000))
    out = queries.downsample(pts, 1000)
    assert len(out) <= 1001 and out[0] == 0 and out[-1] == 4999
    assert queries.downsample([1, 2, 3], 1000) == [1, 2, 3]


def test_meta_lists_classes_in_order():
    m = queries.meta(CFG)
    assert [c["name"] for c in m["size_classes"]][0] == "ULCC/VLCC"
    assert m["size_classes"][-1]["name"] == "Unclassified"
    assert (m["fade_hours"], m["stale_hours"]) == (2, 6)
```

- [ ] **Step 6: Run to verify failure**

Run: `python -m pytest tests/test_queries.py -v`
Expected: FAIL (`ModuleNotFoundError`/`AttributeError: queries`).

- [ ] **Step 7: Implement `api/queries.py`**

```python
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime

import psycopg

from api.filters import VesselFilters, build_where
from common.config import Config

CLUSTER_ZOOM = 5
MAX_FEATURES = 5000
MAX_TRACK_POINTS = 1000

_FROM = "FROM latest_position lp JOIN vessels v ON v.mmsi = lp.mmsi"
_COLS = """v.mmsi, v.name, v.size_class, v.cargo_group, v.laden, v.flag,
    lp.ts, lp.sog, lp.cog, lp.heading, lp.nav_status,
    ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat,
    EXTRACT(EPOCH FROM (now() - lp.ts)) / 3600.0 AS age_h"""
_PROPS = ("mmsi", "name", "size_class", "cargo_group", "laden", "flag", "ts", "sog", "cog", "heading", "nav_status")


def _feature(r: dict) -> dict:
    props = {k: r[k] for k in _PROPS}
    props["age_h"] = float(r["age_h"])
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]}, "properties": props}


def list_vessels(conn: psycopg.Connection, f: VesselFilters, zoom: int | None, cfg: Config) -> dict:
    where, params = build_where(f, cfg.stale_hours)
    if zoom is not None and zoom < CLUSTER_ZOOM:
        cell = 40.0 / (2 ** max(zoom, 0))
        rows = conn.execute(
            f"SELECT count(*) AS count, avg(ST_X(lp.geom)) AS lon, avg(ST_Y(lp.geom)) AS lat "
            f"{_FROM} WHERE {where} GROUP BY ST_SnapToGrid(lp.geom, %s)",
            [*params, cell],
        ).fetchall()
        features = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
             "properties": {"cluster": True, "count": r["count"]}}
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features}
    rows = conn.execute(
        f"SELECT {_COLS} {_FROM} WHERE {where} ORDER BY lp.ts DESC LIMIT %s", [*params, MAX_FEATURES]
    ).fetchall()
    return {"type": "FeatureCollection", "features": [_feature(r) for r in rows]}


def updated_since(conn, f: VesselFilters, since: datetime, cfg: Config, limit: int = 2000):
    where, params = build_where(f, cfg.stale_hours)
    rows = conn.execute(
        f"SELECT {_COLS}, lp.updated_at {_FROM} WHERE {where} AND lp.updated_at > %s "
        f"ORDER BY lp.updated_at LIMIT %s",
        [*params, since, limit],
    ).fetchall()
    newest = rows[-1]["updated_at"] if rows else since
    return [_feature(r) for r in rows], newest


def vessel_detail(conn, mmsi: int) -> dict | None:
    r = conn.execute(
        """SELECT v.*, lp.ts AS pos_ts, ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat,
                  lp.sog, lp.cog, lp.heading, lp.nav_status
           FROM vessels v LEFT JOIN latest_position lp ON lp.mmsi = v.mmsi WHERE v.mmsi = %s""",
        (mmsi,),
    ).fetchone()
    if r is None:
        return None
    position = None
    if r["pos_ts"] is not None:
        position = {k: r[k] for k in ("lon", "lat", "sog", "cog", "heading", "nav_status")}
        position["ts"] = r["pos_ts"]
    out = {k: r[k] for k in ("mmsi", "imo", "name", "callsign", "flag", "ship_type_code", "length_m", "beam_m",
                             "size_class", "cargo_group", "classified_by", "draught_m", "laden",
                             "destination", "eta")}
    out["inferred"] = {"cargo_group": True, "laden": True}
    out["position"] = position
    return out


def split_antimeridian(coords: list) -> list:
    if not coords:
        return []
    lines = [[coords[0]]]
    for prev, cur in zip(coords, coords[1:]):
        if abs(cur[0] - prev[0]) > 180:
            lines.append([])
        lines[-1].append(cur)
    return lines


def downsample(items: list, max_points: int) -> list:
    if len(items) <= max_points:
        return items
    step = len(items) / max_points
    out = [items[int(i * step)] for i in range(max_points)]
    out.append(items[-1])
    return out


def vessel_track(conn, mmsi: int, start: datetime, end: datetime) -> dict:
    rows = conn.execute(
        "SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat FROM positions "
        "WHERE mmsi = %s AND ts >= %s AND ts <= %s ORDER BY ts LIMIT 50000",
        (mmsi, start, end),
    ).fetchall()
    coords = downsample([[r["lon"], r["lat"]] for r in rows], MAX_TRACK_POINTS)
    lines = [ln for ln in split_antimeridian(coords) if len(ln) >= 2]
    return {
        "type": "Feature",
        "geometry": {"type": "MultiLineString", "coordinates": lines},
        "properties": {"mmsi": mmsi, "point_count": len(rows), "from": start, "to": end},
    }


def search(conn, q: str, limit: int = 20) -> list[dict]:
    q = q.strip()
    if len(q) < 2:
        return []
    if q.isdigit():
        if len(q) > 12:
            return []
        n = int(q)
        cond, params = "v.mmsi = %s OR v.imo = %s", [n, n]
    else:
        escaped = re.sub(r"([\\%_])", r"\\\1", q.lower())
        cond, params = "lower(v.name) LIKE %s", [f"%{escaped}%"]
    return conn.execute(
        f"SELECT v.mmsi, v.name, v.imo, v.size_class, v.flag, ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat "
        f"FROM vessels v LEFT JOIN latest_position lp ON lp.mmsi = v.mmsi "
        f"WHERE {cond} ORDER BY v.name LIMIT %s",
        [*params, limit],
    ).fetchall()


_FACETS = {
    "size_class": "v.size_class",
    "cargo_group": "v.cargo_group",
    "laden": "v.laden",
    "flag": "v.flag",
    "nav_status": "lp.nav_status",
}
_LADEN = {True: "laden", False: "ballast", None: "unknown"}


def stats(conn, f: VesselFilters, cfg: Config) -> dict:
    f = replace(f, bbox=None)
    where, params = build_where(f, cfg.stale_hours)
    out: dict = {"total": conn.execute(f"SELECT count(*) AS n {_FROM} WHERE {where}", params).fetchone()["n"]}
    for dim, col in _FACETS.items():
        w, p = build_where(f, cfg.stale_hours, skip=dim)
        rows = conn.execute(f"SELECT {col} AS k, count(*) AS n {_FROM} WHERE {w} GROUP BY 1", p).fetchall()
        counts = {}
        for r in rows:
            key = _LADEN[r["k"]] if dim == "laden" else ("unknown" if r["k"] is None else str(r["k"]))
            counts[key] = r["n"]
        out[dim] = counts
    out["newest_ts"] = conn.execute("SELECT max(ts) AS t FROM latest_position").fetchone()["t"]
    return out


def meta(cfg: Config) -> dict:
    classes = [{"name": c.name, "cargo_group": c.cargo_group} for c in cfg.size_classes]
    classes.append({"name": "Unclassified", "cargo_group": "unknown"})
    return {"size_classes": classes, "fade_hours": cfg.fade_hours, "stale_hours": cfg.stale_hours}
```

- [ ] **Step 8: Run to verify pass**

Run: `python -m pytest -v`
Expected: all tests (Tasks 1-7) PASS.

- [ ] **Step 9: Commit**

```bash
git add api common db tests
git commit -m "feat: API filters and queries (vessels, clusters, stats, search, tracks)"
```

---

### Task 8: API app and websocket

**Files:**
- Create: `api/main.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `api.queries`, `api.filters`, `common.database.database_url`.
- Produces: `api.main.create_app(conninfo: str | None = None, cfg: Config | None = None, poll_seconds: float = 2.0) -> FastAPI`; module-level `app = create_app()` is NOT created (use `uvicorn api.main:create_app --factory`). WS protocol: client sends JSON `{bbox?, size_class?, cargo_group?, laden?, flag?, nav_status?, min_speed?, max_speed?}`; server replies `{"type": "positions", "features": [...]}` whenever matching `latest_position.updated_at` rows change after the subscription.

- [ ] **Step 1: Write failing tests `tests/test_api.py`**

```python
import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from common.database import database_url
from tests.helpers import seed_vessel


@pytest.fixture
def client(db):
    app = create_app(conninfo=database_url(test=True), poll_seconds=0.05)
    with TestClient(app) as c:
        yield c


def test_vessels_endpoint_with_filters_and_bbox(client, db):
    seed_vessel(db, 1, size_class="MR", lon=10, lat=10)
    seed_vessel(db, 2, size_class="Suezmax", lon=50, lat=10)
    r = client.get("/api/vessels", params={"zoom": 8, "bbox": "0,0,20,20", "size_class": ["MR", "VLCC"]})
    assert r.status_code == 200
    assert [f["properties"]["mmsi"] for f in r.json()["features"]] == [1]


def test_bad_bbox_is_422(client):
    assert client.get("/api/vessels", params={"bbox": "1,2,3"}).status_code == 422
    assert client.get("/api/vessels", params={"bbox": "a,b,c,d"}).status_code == 422


def test_detail_404_and_ok(client, db):  # Review Focus 5
    seed_vessel(db, 1, name="ALPHA")
    assert client.get("/api/vessels/1").json()["name"] == "ALPHA"
    assert client.get("/api/vessels/999").status_code == 404


def test_track_defaults_and_404(client, db):
    seed_vessel(db, 1)
    r = client.get("/api/vessels/1/track")
    assert r.status_code == 200 and r.json()["geometry"]["type"] == "MultiLineString"
    assert client.get("/api/vessels/999/track").status_code == 404


def test_search_and_stats_and_meta(client, db):
    seed_vessel(db, 111111111, name="NORDIC MARS")
    assert client.get("/api/search", params={"q": "mars"}).json()[0]["mmsi"] == 111111111
    assert client.get("/api/search", params={"q": ""}).json() == []                 # Review Focus 5
    assert client.get("/api/stats").json()["total"] == 1
    assert client.get("/api/meta").json()["stale_hours"] == 6


def test_ws_pushes_only_matching_updates(client, db):
    seed_vessel(db, 1, lon=10, lat=10)
    seed_vessel(db, 2, lon=80, lat=10)
    with client.websocket_connect("/ws/positions") as ws:
        ws.send_json({"bbox": [0, 0, 20, 20]})
        time.sleep(0.3)
        db.execute("UPDATE latest_position SET updated_at = now() WHERE mmsi = 2")   # outside bbox
        db.execute("UPDATE latest_position SET updated_at = now() WHERE mmsi = 1")   # inside bbox
        msg = ws.receive_json()
        assert msg["type"] == "positions"
        assert [f["properties"]["mmsi"] for f in msg["features"]] == [1]


def test_ws_ignores_garbage_subscription(client, db):
    seed_vessel(db, 1)
    with client.websocket_connect("/ws/positions") as ws:
        ws.send_json({"bbox": "nonsense", "nav_status": ["x"]})
        time.sleep(0.3)
        db.execute("UPDATE latest_position SET updated_at = now()")
        assert ws.receive_json()["type"] == "positions"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL (`ModuleNotFoundError: api.main`).

- [ ] **Step 3: Implement `api/main.py`**

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api import queries
from api.filters import VesselFilters, filters_from_json
from common.config import Config, load_config
from common.database import database_url


def _parse_bbox(raw: str | None):
    if not raw:
        return None
    try:
        w, s, e, n = (float(x) for x in raw.split(","))
    except ValueError:
        raise HTTPException(422, "bbox must be four numbers: west,south,east,north")
    return (w, s, e, n)


def create_app(conninfo: str | None = None, cfg: Config | None = None, poll_seconds: float = 2.0) -> FastAPI:
    cfg = cfg or load_config()
    pool = ConnectionPool(
        conninfo or database_url(),
        kwargs={"row_factory": dict_row, "autocommit": True},
        min_size=1,
        max_size=8,
        open=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool.open()
        yield
        pool.close()

    app = FastAPI(title="Vessel Tracker", lifespan=lifespan)

    def get_conn():
        with pool.connection() as conn:
            yield conn

    def filters_dep(
        bbox: str | None = None,
        size_class: list[str] = Query(default=[]),
        cargo_group: list[str] = Query(default=[]),
        laden: bool | None = None,
        flag: list[str] = Query(default=[]),
        nav_status: list[int] = Query(default=[]),
        min_speed: float | None = None,
        max_speed: float | None = None,
    ) -> VesselFilters:
        return VesselFilters(
            bbox=_parse_bbox(bbox), size_class=tuple(size_class), cargo_group=tuple(cargo_group), laden=laden,
            flag=tuple(flag), nav_status=tuple(nav_status), min_speed=min_speed, max_speed=max_speed,
        )

    @app.get("/api/vessels")
    def vessels(zoom: int | None = None, f: VesselFilters = Depends(filters_dep), conn=Depends(get_conn)):
        return queries.list_vessels(conn, f, zoom, cfg)

    @app.get("/api/vessels/{mmsi}")
    def vessel(mmsi: int, conn=Depends(get_conn)):
        d = queries.vessel_detail(conn, mmsi)
        if d is None:
            raise HTTPException(404, "vessel not found")
        return d

    @app.get("/api/vessels/{mmsi}/track")
    def track(mmsi: int, start: datetime | None = Query(default=None, alias="from"),
              end: datetime | None = Query(default=None, alias="to"), conn=Depends(get_conn)):
        if queries.vessel_detail(conn, mmsi) is None:
            raise HTTPException(404, "vessel not found")
        end = end or datetime.now(timezone.utc)
        start = start or end - timedelta(hours=24)
        return queries.vessel_track(conn, mmsi, start, end)

    @app.get("/api/search")
    def search(q: str = "", conn=Depends(get_conn)):
        return queries.search(conn, q)

    @app.get("/api/stats")
    def stats(f: VesselFilters = Depends(filters_dep), conn=Depends(get_conn)):
        return queries.stats(conn, f, cfg)

    @app.get("/api/meta")
    def meta():
        return queries.meta(cfg)

    def _poll(f: VesselFilters, since: datetime):
        with pool.connection() as conn:
            return queries.updated_since(conn, f, since, cfg)

    @app.websocket("/ws/positions")
    async def ws_positions(ws: WebSocket):
        await ws.accept()
        state = {"filters": VesselFilters(), "since": datetime.now(timezone.utc)}

        async def reader():
            try:
                while True:
                    data = await ws.receive_json()
                    state["filters"] = filters_from_json(data) if isinstance(data, dict) else VesselFilters()
                    state["since"] = datetime.now(timezone.utc)
            except (WebSocketDisconnect, RuntimeError, ValueError):
                return

        task = asyncio.create_task(reader())
        try:
            while not task.done():
                await asyncio.sleep(poll_seconds)
                features, newest = await asyncio.to_thread(_poll, state["filters"], state["since"])
                if features:
                    state["since"] = newest
                    await ws.send_json(jsonable_encoder({"type": "positions", "features": features}))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            task.cancel()

    return app
```

Run the server with: `python -m uvicorn api.main:create_app --factory --port 8000`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS.

- [ ] **Step 5: Smoke test against the dev DB**

Run (background): `python -m uvicorn api.main:create_app --factory --port 8000`, then `curl -s "http://127.0.0.1:8000/api/stats"` and `curl -s "http://127.0.0.1:8000/api/meta"`.
Expected: JSON with `total` and `size_class` counts reflecting what the collector stored in Task 6. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add api tests
git commit -m "feat: FastAPI app with REST endpoints and live websocket"
```

---

### Task 9: Web scaffold and map with vessel markers

**Files:**
- Create: `web/` (Vite React-TS app), `web/vite.config.ts`, `web/src/{types.ts,colors.ts,api.ts,filters.ts,filters.test.ts,App.tsx,main.tsx,index.css}`, `web/src/components/MapView.tsx`

**Interfaces:**
- Produces:
  - `filters.ts`: `Filters` type, `emptyFilters`, `toggle<T>(list: T[], v: T): T[]`, `normalizeBbox(w,s,e,n): [number,number,number,number]`, `filtersToParams(f: Filters, extra?: {bbox?: number[]; zoom?: number}): URLSearchParams`, `CLUSTER_ZOOM = 5`, `NAV_STATUS: Record<number,string>`.
  - `colors.ts`: `SIZE_COLORS: Record<string,string>`, `DEFAULT_COLOR`.
  - `api.ts`: `getJSON<T>(url: string, signal?: AbortSignal): Promise<T>`.
  - `MapView` props: `{ filters: Filters; meta: Meta | null; onSelect: (mmsi: number) => void; track: GeoJSON.Feature | null; flyTo: {lon: number; lat: number; nonce: number} | null; onLiveState?: (s: LiveState) => void }`.

- [ ] **Step 1: Scaffold and install**

Run (from the repo root; the human may want OneDrive paused during `npm install`, which creates many files):
```bash
npm create vite@latest web -- --template react-ts
cd web && npm install && npm install maplibre-gl && npm install -D vitest
```

- [ ] **Step 2: Replace `web/vite.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  test: { environment: "node" },
});
```

Add `"test": "vitest run"` to the `scripts` in `web/package.json`.

- [ ] **Step 3: Write the failing test `web/src/filters.test.ts`**

```ts
import { describe, expect, it } from "vitest";
import { emptyFilters, filtersToParams, normalizeBbox, toggle } from "./filters";

describe("toggle", () => {
  it("adds and removes", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
  });
});

describe("normalizeBbox", () => {
  it("leaves a normal view alone", () => {
    expect(normalizeBbox(10, -5, 20, 5)).toEqual([10, -5, 20, 5]);
  });
  it("wraps longitudes past the antimeridian", () => {
    expect(normalizeBbox(-250, -10, -200, 10)).toEqual([110, -10, 160, 10]);
    expect(normalizeBbox(170, -10, 190, 10)).toEqual([170, -10, -170, 10]);
  });
  it("covers the world when the view spans 360 degrees or more", () => {
    expect(normalizeBbox(-400, -90, 400, 90)).toEqual([-180, -90, 180, 90]);
  });
  it("clamps latitude", () => {
    expect(normalizeBbox(0, -100, 10, 100)).toEqual([0, -90, 10, 90]);
  });
});

describe("filtersToParams", () => {
  it("serializes repeated and scalar params", () => {
    const p = filtersToParams(
      { ...emptyFilters, size_class: ["MR", "Suezmax"], laden: false, nav_status: [0] },
      { bbox: [1, 2, 3, 4], zoom: 7 },
    );
    expect(p.getAll("size_class")).toEqual(["MR", "Suezmax"]);
    expect(p.get("laden")).toBe("false");
    expect(p.getAll("nav_status")).toEqual(["0"]);
    expect(p.get("bbox")).toBe("1,2,3,4");
    expect(p.get("zoom")).toBe("7");
  });
  it("omits empty filters", () => {
    expect(filtersToParams(emptyFilters).toString()).toBe("");
  });
});
```

- [ ] **Step 4: Run to verify failure, then implement `web/src/filters.ts`**

Run: `cd web && npx vitest run` -> FAIL (cannot find `./filters`).

```ts
export const CLUSTER_ZOOM = 5;

export type Filters = {
  size_class: string[];
  cargo_group: string[];
  laden: boolean | null;
  flag: string[];
  nav_status: number[];
  min_speed: number | null;
  max_speed: number | null;
};

export const emptyFilters: Filters = {
  size_class: [], cargo_group: [], laden: null, flag: [], nav_status: [], min_speed: null, max_speed: null,
};

export const NAV_STATUS: Record<number, string> = {
  0: "Under way (engine)", 1: "At anchor", 2: "Not under command", 3: "Restricted maneuverability",
  4: "Constrained by draught", 5: "Moored", 6: "Aground", 7: "Fishing", 8: "Under way (sailing)", 15: "Undefined",
};

export function toggle<T>(list: T[], v: T): T[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

const clampLat = (x: number) => Math.max(-90, Math.min(90, x));
const wrapLon = (x: number) => ((((x + 180) % 360) + 360) % 360) - 180;

export function normalizeBbox(w: number, s: number, e: number, n: number): [number, number, number, number] {
  if (e - w >= 360) return [-180, clampLat(s), 180, clampLat(n)];
  return [wrapLon(w), clampLat(s), wrapLon(e), clampLat(n)];
}

export function filtersToParams(f: Filters, extra: { bbox?: number[]; zoom?: number } = {}): URLSearchParams {
  const p = new URLSearchParams();
  if (extra.bbox) p.set("bbox", extra.bbox.join(","));
  if (extra.zoom !== undefined) p.set("zoom", String(extra.zoom));
  f.size_class.forEach((v) => p.append("size_class", v));
  f.cargo_group.forEach((v) => p.append("cargo_group", v));
  if (f.laden !== null) p.set("laden", String(f.laden));
  f.flag.forEach((v) => p.append("flag", v));
  f.nav_status.forEach((v) => p.append("nav_status", String(v)));
  if (f.min_speed !== null) p.set("min_speed", String(f.min_speed));
  if (f.max_speed !== null) p.set("max_speed", String(f.max_speed));
  return p;
}
```

Run: `cd web && npx vitest run` -> PASS.

- [ ] **Step 5: Create `types.ts`, `colors.ts`, `api.ts`**

```ts
// web/src/types.ts
export type LiveState = "live" | "connecting" | "off";
export type Meta = {
  size_classes: { name: string; cargo_group: string }[];
  fade_hours: number;
  stale_hours: number;
};
export type Stats = {
  total: number;
  newest_ts: string | null;
  size_class: Record<string, number>;
  cargo_group: Record<string, number>;
  laden: Record<string, number>;
  flag: Record<string, number>;
  nav_status: Record<string, number>;
};
export type VesselDetail = {
  mmsi: number; name: string | null; imo: number | null; callsign: string | null; flag: string | null;
  length_m: number | null; beam_m: number | null; size_class: string; cargo_group: string;
  draught_m: number | null; laden: boolean | null; destination: string | null; eta: string | null;
  position: { lon: number; lat: number; ts: string; sog: number | null; cog: number | null;
              heading: number | null; nav_status: number | null } | null;
};
export type SearchHit = {
  mmsi: number; name: string | null; imo: number | null; size_class: string; flag: string | null;
  lon: number | null; lat: number | null;
};
```

```ts
// web/src/colors.ts  (Okabe-Ito: distinguishable for colour-blind viewers on a dark map)
export const SIZE_COLORS: Record<string, string> = {
  "ULCC/VLCC": "#E69F00",
  "Suezmax": "#56B4E9",
  "Aframax/LR2": "#009E73",
  "Panamax/LR1": "#F0E442",
  "MR": "#CC79A7",
  "Handy/small": "#D55E00",
  "Unclassified": "#999999",
};
export const DEFAULT_COLOR = "#999999";
```

```ts
// web/src/api.ts
export async function getJSON<T>(url: string, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}
```

- [ ] **Step 6: GATE - confirm the map tile service**

Ask the human: "The map's dark basemap loads its style and tiles from the external service `basemaps.cartocdn.com` (CARTO Dark Matter, free, attribution required). OK to reference it?" Proceed only after a yes. If declined, ask which basemap to use instead.

- [ ] **Step 7: Create `web/src/components/MapView.tsx`**

```tsx
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import { getJSON } from "../api";
import { DEFAULT_COLOR, SIZE_COLORS } from "../colors";
import { CLUSTER_ZOOM, filtersToParams, normalizeBbox, type Filters } from "../filters";
import type { LiveState, Meta } from "../types";

type Props = {
  filters: Filters;
  meta: Meta | null;
  onSelect: (mmsi: number) => void;
  track: GeoJSON.Feature | null;
  flyTo: { lon: number; lat: number; nonce: number } | null;
  onLiveState?: (s: LiveState) => void;
};

const STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function triangle(solid: boolean): ImageData {
  const s = 32;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const g = c.getContext("2d")!;
  g.beginPath();
  g.moveTo(s / 2, 3); g.lineTo(s - 6, s - 4); g.lineTo(s / 2, s - 9); g.lineTo(6, s - 4);
  g.closePath();
  if (solid) { g.fillStyle = "#000"; g.fill(); } else { g.lineWidth = 3; g.strokeStyle = "#000"; g.stroke(); }
  return g.getImageData(0, 0, s, s);
}

export default function MapView({ filters, meta, onSelect, track, flyTo }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [view, setView] = useState<{ bbox: number[]; zoom: number } | null>(null);
  const featuresRef = useRef<Map<number, GeoJSON.Feature>>(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fadeHours = meta?.fade_hours ?? 2;

  // create the map once
  useEffect(() => {
    const map = new maplibregl.Map({ container: el.current!, style: STYLE, center: [0, 25], zoom: 2, attributionControl: { compact: true } });
    mapRef.current = map;
    const updateView = () => {
      const b = map.getBounds();
      setView({ bbox: normalizeBbox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()), zoom: Math.floor(map.getZoom()) });
    };
    map.on("load", () => {
      map.addImage("tri-solid", triangle(true), { sdf: true });
      map.addImage("tri-hollow", triangle(false), { sdf: true });
      map.addSource("vessels", { type: "geojson", data: EMPTY });
      map.addSource("track", { type: "geojson", data: EMPTY });
      map.addLayer({ id: "track", type: "line", source: "track", paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.8 } });
      map.addLayer({
        id: "clusters", type: "circle", source: "vessels", filter: ["has", "cluster"],
        paint: {
          "circle-color": "#3b82f6", "circle-opacity": 0.65,
          "circle-radius": ["step", ["get", "count"], 12, 10, 16, 50, 22, 200, 28],
        },
      });
      map.addLayer({
        id: "cluster-count", type: "symbol", source: "vessels", filter: ["has", "cluster"],
        layout: { "text-field": ["get", "count"], "text-size": 12, "text-allow-overlap": true },
        paint: { "text-color": "#fff" },
      });
      map.addLayer({
        id: "vessels", type: "symbol", source: "vessels", filter: ["!", ["has", "cluster"]],
        layout: {
          "icon-image": ["case", ["==", ["get", "laden"], false], "tri-hollow", "tri-solid"],
          "icon-rotate": ["to-number", ["get", "cog"], 0],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-size": 0.55,
        },
        paint: {
          "icon-color": ["match", ["get", "size_class"],
            ...Object.entries(SIZE_COLORS).flat(), DEFAULT_COLOR],
          "icon-opacity": ["case", [">", ["to-number", ["get", "age_h"], 0], fadeHours], 0.35,
            ["==", ["get", "laden"], null], 0.6, 1],
        },
      });
      map.on("click", "vessels", (e) => {
        const mmsi = e.features?.[0]?.properties?.mmsi;
        if (mmsi) onSelectRef.current(Number(mmsi));
      });
      map.on("click", "clusters", (e) => {
        const c = (e.features?.[0]?.geometry as GeoJSON.Point).coordinates as [number, number];
        map.easeTo({ center: c, zoom: map.getZoom() + 2 });
      });
      for (const layer of ["vessels", "clusters"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
      map.on("moveend", updateView);
      updateView();
      setReady(true);
    });
    return () => map.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // fetch vessels whenever the view or filters change
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !view) return;
    const ctl = new AbortController();
    const params = filtersToParams(filters, { bbox: view.bbox, zoom: view.zoom });
    getJSON<GeoJSON.FeatureCollection>(`/api/vessels?${params}`, ctl.signal)
      .then((fc) => {
        featuresRef.current = new Map(
          fc.features.filter((f) => !f.properties?.cluster).map((f) => [f.properties!.mmsi as number, f]),
        );
        (map.getSource("vessels") as maplibregl.GeoJSONSource).setData(fc);
      })
      .catch((e) => { if (e.name !== "AbortError") console.error(e); });
    return () => ctl.abort();
  }, [ready, view, filters]);

  useEffect(() => {
    const src = mapRef.current?.getSource("track") as maplibregl.GeoJSONSource | undefined;
    src?.setData(track ?? EMPTY);
  }, [track, ready]);

  useEffect(() => {
    if (flyTo) mapRef.current?.flyTo({ center: [flyTo.lon, flyTo.lat], zoom: Math.max(mapRef.current.getZoom(), 8) });
  }, [flyTo]);

  void CLUSTER_ZOOM;
  return <div ref={el} className="map" />;
}
```

(`onLiveState` is wired in Task 12; the `CLUSTER_ZOOM` reference is replaced then.)

- [ ] **Step 8: Replace `web/src/App.tsx`, `main.tsx`, `index.css`**

```tsx
// web/src/App.tsx
import { useEffect, useState } from "react";
import { getJSON } from "./api";
import MapView from "./components/MapView";
import { emptyFilters, type Filters } from "./filters";
import type { Meta } from "./types";

export default function App() {
  const [filters] = useState<Filters>(emptyFilters);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => { getJSON<Meta>("/api/meta").then(setMeta).catch(console.error); }, []);

  return (
    <div className="app">
      <MapView filters={filters} meta={meta} onSelect={setSelected} track={null} flyTo={null} />
      {selected !== null && <div className="debug">selected {selected}</div>}
    </div>
  );
}
```

```tsx
// web/src/main.tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
```

```css
/* web/src/index.css */
html, body, #root { height: 100%; margin: 0; }
body { background: #0b1220; color: #e5e7eb; font-family: system-ui, sans-serif; font-size: 13px; }
.app { position: relative; height: 100%; }
.map { position: absolute; inset: 0; }
.debug { position: absolute; top: 8px; right: 8px; background: #111827; padding: 6px 10px; border-radius: 6px; }
```

- [ ] **Step 9: Type-check, build and verify in the browser**

Run: `cd web && npm run build` -> expect no TypeScript errors.
Manual check (start API with `python -m uvicorn api.main:create_app --factory --port 8000`, collector running, `cd web && npm run dev`, open the printed URL): the dark map loads; zoomed out shows blue cluster bubbles with counts; zooming past level 5 shows arrow markers in size-class colours; clicking a marker shows `selected <mmsi>`; clicking a cluster zooms in. Report what you observed; if the collector has not stored data yet, say so instead of claiming success.

- [ ] **Step 10: Commit**

```bash
git add web
git commit -m "feat: web scaffold with MapLibre map, clusters and vessel markers"
```

---

### Task 10: Breakdown and filter panel

**Files:**
- Create: `web/src/components/FilterPanel.tsx`
- Modify: `web/src/App.tsx`, `web/src/index.css`

**Interfaces:**
- Consumes: `Filters`, `toggle`, `filtersToParams`, `SIZE_COLORS`, `Meta`, `Stats`, `NAV_STATUS`, `getJSON`.
- Produces: `FilterPanel` props `{ filters: Filters; onChange: (f: Filters) => void; meta: Meta | null; onStats?: (s: Stats | null) => void }`.

- [ ] **Step 1: Create `FilterPanel.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { SIZE_COLORS } from "../colors";
import { emptyFilters, filtersToParams, NAV_STATUS, toggle, type Filters } from "../filters";
import type { Meta, Stats } from "../types";

const CARGO_LABELS: Record<string, string> = {
  crude: "Crude", mostly_crude: "Mostly crude", crude_or_products: "Crude or products",
  mostly_products: "Mostly products", products: "Products", products_coastal: "Products / coastal", unknown: "Unknown",
};

type Props = { filters: Filters; onChange: (f: Filters) => void; meta: Meta | null; onStats?: (s: Stats | null) => void };

export default function FilterPanel({ filters, onChange, meta, onStats }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    const ctl = new AbortController();
    const load = () =>
      getJSON<Stats>(`/api/stats?${filtersToParams(filters)}`, ctl.signal)
        .then((s) => { setStats(s); onStats?.(s); })
        .catch((e) => { if (e.name !== "AbortError") { setStats(null); onStats?.(null); } });
    load();
    const t = setInterval(load, 15000);
    return () => { ctl.abort(); clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const n = (m: Record<string, number> | undefined, k: string) => m?.[k] ?? 0;
  const anyActive = JSON.stringify(filters) !== JSON.stringify(emptyFilters);
  const flags = Object.entries(stats?.flag ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k]) => k);
  for (const f of filters.flag) if (!flags.includes(f)) flags.push(f);

  const row = (key: string, label: string, count: number, active: boolean, onClick: () => void, color?: string) => (
    <button key={key} className={`row ${active ? "active" : ""}`} onClick={onClick}>
      {color && <span className="swatch" style={{ background: color }} />}
      <span className="label">{label}</span>
      <span className="count">{count.toLocaleString()}</span>
    </button>
  );

  return (
    <aside className="panel left">
      <h1>Tankers <small>{stats ? stats.total.toLocaleString() : "-"}</small></h1>
      {anyActive && <button className="clear" onClick={() => onChange(emptyFilters)}>Clear filters</button>}

      <h2>Size class</h2>
      {(meta?.size_classes ?? []).map((c) =>
        row(c.name, c.name, n(stats?.size_class, c.name), filters.size_class.includes(c.name),
          () => onChange({ ...filters, size_class: toggle(filters.size_class, c.name) }), SIZE_COLORS[c.name]))}

      <h2>Cargo group <em>inferred</em></h2>
      {Object.keys(CARGO_LABELS).map((k) =>
        row(k, CARGO_LABELS[k], n(stats?.cargo_group, k), filters.cargo_group.includes(k),
          () => onChange({ ...filters, cargo_group: toggle(filters.cargo_group, k) })))}

      <h2>Laden / ballast <em>estimated</em></h2>
      {row("laden", "Laden", n(stats?.laden, "laden"), filters.laden === true,
        () => onChange({ ...filters, laden: filters.laden === true ? null : true }))}
      {row("ballast", "Ballast", n(stats?.laden, "ballast"), filters.laden === false,
        () => onChange({ ...filters, laden: filters.laden === false ? null : false }))}

      <h2>Flag</h2>
      {flags.map((f) => row(f, f, n(stats?.flag, f), filters.flag.includes(f),
        () => onChange({ ...filters, flag: toggle(filters.flag, f) })))}

      <h2>Status</h2>
      {Object.keys(stats?.nav_status ?? {}).sort((a, b) => Number(a) - Number(b)).map((k) =>
        row(k, NAV_STATUS[Number(k)] ?? `Status ${k}`, n(stats?.nav_status, k), filters.nav_status.includes(Number(k)),
          () => onChange({ ...filters, nav_status: toggle(filters.nav_status, Number(k)) })))}
    </aside>
  );
}
```

- [ ] **Step 2: Wire into `App.tsx`** - change `const [filters] = useState` to `const [filters, setFilters] = useState`, import `FilterPanel`, and render `<FilterPanel filters={filters} onChange={setFilters} meta={meta} />` before `<MapView ...>`.

- [ ] **Step 3: Add styles to `index.css`**

```css
.panel { position: absolute; z-index: 2; background: rgba(17, 24, 39, 0.92); border: 1px solid #1f2937; border-radius: 8px; padding: 10px; overflow-y: auto; max-height: calc(100% - 16px); }
.panel.left { top: 8px; left: 8px; width: 250px; }
.panel h1 { font-size: 15px; margin: 0 0 6px; display: flex; justify-content: space-between; }
.panel h1 small { color: #9ca3af; font-weight: 400; }
.panel h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #9ca3af; margin: 12px 0 4px; }
.panel h2 em { font-style: normal; color: #f59e0b; margin-left: 4px; text-transform: none; }
.row { display: flex; align-items: center; gap: 8px; width: 100%; background: none; border: 0; border-radius: 4px; color: inherit; padding: 4px 6px; cursor: pointer; text-align: left; font: inherit; }
.row:hover { background: #1f2937; }
.row.active { background: #1d4ed8; }
.row .label { flex: 1; }
.row .count { color: #9ca3af; font-variant-numeric: tabular-nums; }
.row.active .count { color: #fff; }
.swatch { width: 10px; height: 10px; border-radius: 2px; }
.clear { background: #374151; border: 0; color: inherit; border-radius: 4px; padding: 4px 8px; cursor: pointer; margin-bottom: 4px; }
```

- [ ] **Step 4: Build and verify**

Run: `cd web && npm run build && npx vitest run` -> no errors.
Manual: the left panel lists the size classes with counts; clicking "MR" filters the map to MR vessels and the other classes keep their counts while cargo-group/laden counts shrink to match; "Clear filters" resets. Report what you observed.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat: breakdown and filter panel with faceted counts"
```

---

### Task 11: Search, vessel panel and tracks

**Files:**
- Create: `web/src/components/SearchBar.tsx`, `web/src/components/VesselPanel.tsx`
- Modify: `web/src/App.tsx`, `web/src/index.css`

**Interfaces:**
- Consumes: `SearchHit`, `VesselDetail`, `getJSON`, `NAV_STATUS`.
- Produces: `SearchBar` props `{ onPick: (hit: SearchHit) => void }`; `VesselPanel` props `{ mmsi: number; onClose: () => void; onTrack: (t: GeoJSON.Feature | null) => void }`.

- [ ] **Step 1: Create `SearchBar.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getJSON } from "../api";
import type { SearchHit } from "../types";

export default function SearchBar({ onPick }: { onPick: (h: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);

  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return; }
    const ctl = new AbortController();
    const t = setTimeout(() => {
      getJSON<SearchHit[]>(`/api/search?q=${encodeURIComponent(q.trim())}`, ctl.signal)
        .then(setHits)
        .catch((e) => { if (e.name !== "AbortError") setHits([]); });
    }, 250);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);

  return (
    <div className="search">
      <input value={q} placeholder="Search name, MMSI or IMO" onChange={(e) => setQ(e.target.value)} />
      {q.trim().length >= 2 && (
        <ul>
          {hits.length === 0 && <li className="none">No matches</li>}
          {hits.map((h) => (
            <li key={h.mmsi}>
              <button onClick={() => { onPick(h); setQ(""); setHits([]); }}>
                {h.name || "(unnamed)"} <small>{h.size_class} - MMSI {h.mmsi}{h.imo ? ` - IMO ${h.imo}` : ""}</small>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create `VesselPanel.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { NAV_STATUS } from "../filters";
import type { VesselDetail } from "../types";

const RANGES = [{ label: "24h", hours: 24 }, { label: "7d", hours: 168 }, { label: "30d", hours: 720 }];
const dash = (v: unknown) => (v === null || v === undefined || v === "" ? "-" : String(v));

export default function VesselPanel({ mmsi, onClose, onTrack }: {
  mmsi: number; onClose: () => void; onTrack: (t: GeoJSON.Feature | null) => void;
}) {
  const [v, setV] = useState<VesselDetail | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<number | null>(null);
  const [trackInfo, setTrackInfo] = useState<string>("");

  useEffect(() => {
    setV(null); setError(false); setRange(null); setTrackInfo(""); onTrack(null);
    getJSON<VesselDetail>(`/api/vessels/${mmsi}`).then(setV).catch(() => setError(true));
    return () => onTrack(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mmsi]);

  useEffect(() => {
    if (range === null) { onTrack(null); setTrackInfo(""); return; }
    const to = new Date();
    const from = new Date(to.getTime() - range * 3600_000);
    getJSON<GeoJSON.Feature>(`/api/vessels/${mmsi}/track?from=${from.toISOString()}&to=${to.toISOString()}`)
      .then((t) => {
        onTrack(t);
        const n = t.properties?.point_count ?? 0;
        setTrackInfo(n < 2 ? "No track recorded in this period (history only exists while the collector runs)" : `${n} positions`);
      })
      .catch(() => setTrackInfo("Could not load track"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, mmsi]);

  const p = v?.position;
  return (
    <aside className="panel right">
      <button className="close" onClick={onClose} aria-label="Close">x</button>
      {error && <p>Vessel not found.</p>}
      {!v && !error && <p>Loading...</p>}
      {v && (
        <>
          <h1>{v.name || "(unnamed)"}</h1>
          <dl>
            <dt>Size class</dt><dd>{v.size_class}</dd>
            <dt>Cargo group <em>inferred</em></dt><dd>{v.cargo_group.replace(/_/g, " ")}</dd>
            <dt>Laden <em>estimated</em></dt><dd>{v.laden === null ? "-" : v.laden ? "Laden" : "Ballast"}</dd>
            <dt>Flag</dt><dd>{dash(v.flag)}</dd>
            <dt>MMSI / IMO</dt><dd>{v.mmsi} / {dash(v.imo)}</dd>
            <dt>Dimensions</dt><dd>{v.length_m ? `${v.length_m} x ${v.beam_m ?? "-"} m` : "-"}</dd>
            <dt>Draught</dt><dd>{v.draught_m ? `${v.draught_m} m` : "-"}</dd>
            <dt>Destination</dt><dd>{dash(v.destination)}</dd>
            <dt>ETA</dt><dd>{v.eta ? new Date(v.eta).toLocaleString() : "-"}</dd>
            <dt>Speed / course</dt><dd>{p ? `${dash(p.sog)} kn / ${dash(p.cog)} deg` : "-"}</dd>
            <dt>Status</dt><dd>{p?.nav_status != null ? (NAV_STATUS[p.nav_status] ?? p.nav_status) : "-"}</dd>
            <dt>Last seen</dt><dd>{p ? new Date(p.ts).toLocaleString() : "-"}</dd>
          </dl>
          <div className="tracks">
            <span>Track</span>
            {RANGES.map((r) => (
              <button key={r.label} className={range === r.hours ? "on" : ""} onClick={() => setRange(range === r.hours ? null : r.hours)}>{r.label}</button>
            ))}
          </div>
          {trackInfo && <p className="muted">{trackInfo}</p>}
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 3: Update `App.tsx`**

Add state `const [track, setTrack] = useState<GeoJSON.Feature | null>(null);` and `const [flyTo, setFlyTo] = useState<{lon:number;lat:number;nonce:number}|null>(null);`. Render:

```tsx
<SearchBar onPick={(h) => { setSelected(h.mmsi); if (h.lon !== null && h.lat !== null) setFlyTo({ lon: h.lon, lat: h.lat, nonce: Date.now() }); }} />
{selected !== null && <VesselPanel mmsi={selected} onClose={() => setSelected(null)} onTrack={setTrack} />}
<MapView ... track={track} flyTo={flyTo} />
```
and delete the temporary `.debug` div. Import both components.

- [ ] **Step 4: Add styles to `index.css`**

```css
.panel.right { top: 8px; right: 8px; width: 290px; }
.close { position: absolute; top: 6px; right: 8px; background: none; border: 0; color: #9ca3af; cursor: pointer; font-size: 16px; }
dl { display: grid; grid-template-columns: 110px 1fr; gap: 4px 8px; margin: 8px 0; }
dt { color: #9ca3af; } dt em { color: #f59e0b; font-style: normal; font-size: 10px; display: block; }
dd { margin: 0; word-break: break-word; }
.tracks { display: flex; gap: 6px; align-items: center; }
.tracks button { background: #374151; color: inherit; border: 0; border-radius: 4px; padding: 3px 8px; cursor: pointer; }
.tracks button.on { background: #1d4ed8; }
.muted { color: #9ca3af; }
.search { position: absolute; z-index: 3; top: 8px; left: 50%; transform: translateX(-50%); width: 320px; }
.search input { width: 100%; box-sizing: border-box; padding: 8px 10px; border-radius: 8px; border: 1px solid #374151; background: #111827; color: inherit; font: inherit; }
.search ul { list-style: none; margin: 4px 0 0; padding: 0; background: #111827; border: 1px solid #374151; border-radius: 8px; max-height: 300px; overflow-y: auto; }
.search li button { display: block; width: 100%; text-align: left; background: none; border: 0; color: inherit; padding: 6px 10px; cursor: pointer; font: inherit; }
.search li button:hover { background: #1f2937; }
.search li small { color: #9ca3af; display: block; }
.search .none { padding: 8px 10px; color: #9ca3af; }
```

- [ ] **Step 5: Build and verify**

Run: `cd web && npm run build` -> no errors.
Manual: search a known tanker name or MMSI, pick it, the map flies there and the right panel opens with details, "inferred"/"estimated" tags visible; click 24h under Track and a white line appears (or the "no track recorded" message if the collector has been running only briefly); typing `%%` shows "No matches"; closing the panel clears the track. Report what you observed.

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "feat: search, vessel detail panel and track display"
```

---

### Task 12: Live updates, status chip, stale handling

**Files:**
- Create: `web/src/useLiveSocket.ts`, `web/src/components/StatusChip.tsx`
- Modify: `web/src/components/MapView.tsx`, `web/src/App.tsx`, `web/src/index.css`

**Interfaces:**
- Consumes: `LiveState`, `Stats`, `CLUSTER_ZOOM`, `filtersToParams` fields.
- Produces: `useLiveSocket({ enabled: boolean; payload: object | null; onFeatures: (f: GeoJSON.Feature[]) => void }): LiveState`; `StatusChip` props `{ live: LiveState; newestTs: string | null }`.

- [ ] **Step 1: Create `useLiveSocket.ts`**

```ts
import { useEffect, useRef, useState } from "react";
import type { LiveState } from "./types";

type Opts = { enabled: boolean; payload: object | null; onFeatures: (f: GeoJSON.Feature[]) => void };

export function useLiveSocket({ enabled, payload, onFeatures }: Opts): LiveState {
  const [state, setState] = useState<LiveState>("off");
  const wsRef = useRef<WebSocket | null>(null);
  const payloadRef = useRef(payload);
  payloadRef.current = payload;
  const cbRef = useRef(onFeatures);
  cbRef.current = onFeatures;

  useEffect(() => {
    if (!enabled) { setState("off"); return; }
    let closed = false;
    let retry = 1000;
    let timer: number | undefined;
    const open = () => {
      setState("connecting");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/positions`);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 1000;
        setState("live");
        if (payloadRef.current) ws.send(JSON.stringify(payloadRef.current));
      };
      ws.onmessage = (ev) => {
        try {
          const m = JSON.parse(ev.data);
          if (m.type === "positions") cbRef.current(m.features);
        } catch { /* ignore malformed frame */ }
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (closed) return;
        setState("connecting");
        timer = window.setTimeout(open, retry);
        retry = Math.min(retry * 2, 30000);
      };
    };
    open();
    return () => { closed = true; window.clearTimeout(timer); wsRef.current?.close(); setState("off"); };
  }, [enabled]);

  useEffect(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && payload) ws.send(JSON.stringify(payload));
  }, [payload]);

  return state;
}
```

- [ ] **Step 2: Create `StatusChip.tsx`**

```tsx
import { useEffect, useState } from "react";
import type { LiveState } from "../types";

export default function StatusChip({ live, newestTs }: { live: LiveState; newestTs: string | null }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 5000); return () => clearInterval(t); }, []);
  const age = newestTs ? Math.max(0, Math.round((Date.now() - new Date(newestTs).getTime()) / 1000)) : null;
  const human = age === null ? "no data yet" : age < 90 ? `${age}s ago` : age < 5400 ? `${Math.round(age / 60)} min ago` : `${Math.round(age / 3600)} h ago`;
  const stale = age === null || age > 300;
  const dot = stale ? "#f59e0b" : live === "live" ? "#10b981" : "#9ca3af";
  const label = live === "live" ? "Live" : live === "connecting" ? "Reconnecting" : "Zoom in for live updates";
  return (
    <div className="chip">
      <span className="dot" style={{ background: dot }} />
      {label} - newest AIS message {human}{stale && age !== null ? " (feed may be down)" : ""}
    </div>
  );
}
```

- [ ] **Step 3: Wire the socket into `MapView.tsx`**

Add imports `useMemo` (from react) and `useLiveSocket`. Inside `MapView`, after the fetch effect:

```tsx
  const payload = useMemo(() => (view ? { bbox: view.bbox, ...filters } : null), [view, filters]);
  const live = useLiveSocket({
    enabled: ready && !!view && view.zoom >= CLUSTER_ZOOM,
    payload,
    onFeatures: (feats) => {
      const src = mapRef.current?.getSource("vessels") as maplibregl.GeoJSONSource | undefined;
      if (!src) return;
      for (const f of feats) featuresRef.current.set(f.properties!.mmsi as number, f);
      src.setData({ type: "FeatureCollection", features: [...featuresRef.current.values()] });
    },
  });
  useEffect(() => { onLiveState?.(live); }, [live, onLiveState]);
```
and delete the `void CLUSTER_ZOOM;` line; add `onLiveState` to the destructured props. Note: the websocket sends only `updated_at`-changed rows after subscribing, so the REST fetch remains the source of the initial set; `featuresRef` is reset by each REST fetch (already done in Task 9).

- [ ] **Step 4: Wire into `App.tsx`**

Add `const [live, setLive] = useState<LiveState>("off");` and `const [stats, setStats] = useState<Stats | null>(null);`. Pass `onStats={setStats}` to `FilterPanel` and `onLiveState={setLive}` to `MapView`, and render `<StatusChip live={live} newestTs={stats?.newest_ts ?? null} />`. Import the types and component.

- [ ] **Step 5: Add chip style**

```css
.chip { position: absolute; z-index: 3; bottom: 24px; left: 50%; transform: translateX(-50%); background: rgba(17, 24, 39, 0.92); border: 1px solid #374151; border-radius: 999px; padding: 5px 12px; display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
```

- [ ] **Step 6: Build and verify**

Run: `cd web && npm run build` -> no errors.
Manual (collector and API running): zoom in past level 5; the chip shows "Live" and the age of the newest message stays small; markers move/appear without refreshing; stop the API and confirm the chip changes to "Reconnecting", then restart it and confirm it returns to "Live"; stop the collector and confirm the chip turns amber with "(feed may be down)" after about 5 minutes. Faded markers (older than 2 h) appear dimmer. Report what you observed; note anything you could not check.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat: live websocket updates, status chip and stale fading"
```

---

### Task 13: README, hosting notes and end-to-end check

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** covering exactly these sections (real commands, no placeholders):

1. **What it is** - tanker-only live map; inferred cargo/laden caveats; free AIS limits (patchy coverage, history only from first run).
2. **Prerequisites** - Python 3.11+, Node 20+, PostgreSQL with PostGIS.
3. **One-time setup** - create `vessel_tracker` and `vessel_tracker_test` databases and `CREATE EXTENSION postgis` (human runs these), set `DATABASE_URL`, `TEST_DATABASE_URL`, `AISSTREAM_API_KEY` as environment variables (never commit them; `.env*` is git-ignored), create the virtualenv outside OneDrive (`python -m venv %LOCALAPPDATA%\vessel-tracker-venv`), `pip install -e ".[dev]"`, `cd web && npm install`, `python -m db.migrate`.
4. **Run** - three terminals: `python -m collector.main`; `python -m uvicorn api.main:create_app --factory --port 8000`; `cd web && npm run dev` then open the printed URL.
5. **Tests** - `python -m pytest`, `cd web && npm test`; DB tests skip without `TEST_DATABASE_URL`.
6. **Tuning classification** - edit `config/classification.yaml`; thresholds are starting values; explain Aframax/LR2 ambiguity and that chemical/LPG/LNG carriers mix into the classes.
7. **Retention** - `python -m db.prune --yes` drops position partitions older than `retention_months`.
8. **OneDrive note** - the repo is in OneDrive; the virtualenv lives outside it; `web/node_modules` is large, so pause sync during `npm install` or move the project outside OneDrive.
9. **Hosting later** - same two processes plus a built UI (`npm run build`, serve `web/dist` and reverse-proxy `/api` and `/ws` to uvicorn); set the same environment variables on the host; add authentication in front before exposing publicly (v1 has none); swap data feeds by adding a class implementing `collector.providers.base.AISProvider` and using it in `collector/main.py`.

- [ ] **Step 2: End-to-end check**

With the collector running for at least 10 minutes: run `python -m pytest` (expect all pass or DB tests skipped only if `TEST_DATABASE_URL` is unset - say so explicitly), `cd web && npm test && npm run build`, then repeat the manual checks from Tasks 9-12 in one pass and note any that failed or that could not be verified (for example, no laden vessels yet).

- [ ] **Step 3: Commit and push (ask first)**

```bash
git add README.md
git commit -m "docs: README with setup, run, tuning and hosting notes"
```
Ask the human before `git push origin main`.
