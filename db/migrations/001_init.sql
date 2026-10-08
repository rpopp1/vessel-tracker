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
