-- Mubadala ACCESS EcoMonitor replacement schema
-- Target stack: PostgreSQL + PostGIS + TimescaleDB
-- This schema is designed to replace the current direct MongoDB reads over time
-- while supporting the same map, summary, metadata, export, and trend workflows.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

CREATE SCHEMA IF NOT EXISTS ecomonitor;
SET search_path TO ecomonitor, public;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'station_privacy') THEN
    CREATE TYPE station_privacy AS ENUM ('public', 'private');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'station_status') THEN
    CREATE TYPE station_status AS ENUM ('Active', 'Maintenance', 'Decommissioned', 'Unknown');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'device_type') THEN
    CREATE TYPE device_type AS ENUM (
      'IoTBox',
      'Meteorological',
      'Buoy',
      'Fidas_Palas',
      'SBNTransect',
      'JWCruise',
      'underwater_probe',
      'coral_reef',
      'Unknown'
    );
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS stations (
  station_pk            BIGSERIAL PRIMARY KEY,
  station_id            TEXT NOT NULL UNIQUE,
  station_num           INTEGER,
  name                  TEXT NOT NULL,
  device_type           device_type NOT NULL DEFAULT 'Unknown',
  status                station_status NOT NULL DEFAULT 'Unknown',
  privacy               station_privacy NOT NULL DEFAULT 'public',
  latitude              DOUBLE PRECISION,
  longitude             DOUBLE PRECISION,
  geom                  geometry(Point, 4326),
  location_text         TEXT,
  model                 TEXT,
  sensors_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_calibration      TIMESTAMPTZ,
  metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_stations_device_status_privacy ON stations (device_type, status, privacy);
CREATE INDEX IF NOT EXISTS ix_stations_name_trgm ON stations USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_stations_geom ON stations USING gist (geom);
CREATE INDEX IF NOT EXISTS ix_stations_station_num ON stations (station_num);

CREATE TABLE IF NOT EXISTS metric_catalog (
  metric_key            TEXT PRIMARY KEY,
  display_label         TEXT NOT NULL,
  canonical_label       TEXT NOT NULL,
  unit                  TEXT,
  category              TEXT NOT NULL,
  description           TEXT,
  metadata_json         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS station_metric_definitions (
  station_pk            BIGINT NOT NULL REFERENCES stations(station_pk) ON DELETE CASCADE,
  metric_key            TEXT NOT NULL REFERENCES metric_catalog(metric_key) ON DELETE CASCADE,
  source_path           TEXT,
  aggregation_mode      TEXT NOT NULL DEFAULT 'mean',
  thresholds_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (station_pk, metric_key)
);

CREATE TABLE IF NOT EXISTS station_health_snapshots (
  snapshot_id           BIGSERIAL PRIMARY KEY,
  station_pk            BIGINT NOT NULL REFERENCES stations(station_pk) ON DELETE CASCADE,
  observed_at           TIMESTAMPTZ NOT NULL,
  status                station_status NOT NULL,
  freshness_minutes     INTEGER,
  sensor_health_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
  notes                 TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_station_health_latest ON station_health_snapshots (station_pk, observed_at DESC);

-- Generic wide observations table for most charting needs.
CREATE TABLE IF NOT EXISTS observations (
  observation_id        BIGSERIAL PRIMARY KEY,
  station_pk            BIGINT NOT NULL REFERENCES stations(station_pk) ON DELETE CASCADE,
  observed_at           TIMESTAMPTZ NOT NULL,
  metric_key            TEXT NOT NULL REFERENCES metric_catalog(metric_key) ON DELETE RESTRICT,
  sensor_key            TEXT,
  value_numeric         DOUBLE PRECISION,
  value_text            TEXT,
  depth_m               DOUBLE PRECISION,
  latitude              DOUBLE PRECISION,
  longitude             DOUBLE PRECISION,
  quality_flag          TEXT,
  source_record_id      TEXT,
  payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb
);
SELECT create_hypertable('observations', 'observed_at', if_not_exists => TRUE, migrate_data => FALSE);
CREATE INDEX IF NOT EXISTS ix_observations_station_metric_time ON observations (station_pk, metric_key, observed_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_observations_dedup ON observations (station_pk, observed_at, metric_key, COALESCE(sensor_key, ''), COALESCE(depth_m, -9999999.0));
CREATE INDEX IF NOT EXISTS ix_observations_station_sensor_time ON observations (station_pk, sensor_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_observations_payload ON observations USING gin (payload_json);

-- Buoy profiles are depth arrays in the current Mongo schema. Keep them as dedicated rows too.
CREATE TABLE IF NOT EXISTS buoy_profiles (
  station_pk            BIGINT NOT NULL REFERENCES stations(station_pk) ON DELETE CASCADE,
  observed_at           TIMESTAMPTZ NOT NULL,
  metric_key            TEXT NOT NULL REFERENCES metric_catalog(metric_key) ON DELETE RESTRICT,
  profile_index         INTEGER NOT NULL,
  depth_m               DOUBLE PRECISION,
  value_numeric         DOUBLE PRECISION,
  payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (station_pk, observed_at, metric_key, profile_index)
);
SELECT create_hypertable('buoy_profiles', 'observed_at', if_not_exists => TRUE, migrate_data => FALSE);
CREATE INDEX IF NOT EXISTS ix_buoy_profiles_station_metric_time ON buoy_profiles (station_pk, metric_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS detected_events (
  event_id              BIGSERIAL PRIMARY KEY,
  station_pk            BIGINT REFERENCES stations(station_pk) ON DELETE CASCADE,
  event_type            TEXT NOT NULL,
  metric_key            TEXT,
  started_at            TIMESTAMPTZ NOT NULL,
  ended_at              TIMESTAMPTZ,
  peak_value            DOUBLE PRECISION,
  severity_label        TEXT,
  message               TEXT,
  payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_detected_events_station_time ON detected_events (station_pk, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_detected_events_type_time ON detected_events (event_type, started_at DESC);

CREATE MATERIALIZED VIEW IF NOT EXISTS station_latest_metric_values AS
SELECT DISTINCT ON (o.station_pk, o.metric_key, COALESCE(o.sensor_key, ''))
  o.station_pk,
  o.metric_key,
  COALESCE(o.sensor_key, '') AS sensor_key,
  o.observed_at,
  o.value_numeric,
  o.value_text,
  o.quality_flag
FROM observations o
ORDER BY o.station_pk, o.metric_key, COALESCE(o.sensor_key, ''), o.observed_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS ux_station_latest_metric_values
  ON station_latest_metric_values (station_pk, metric_key, sensor_key);

CREATE MATERIALIZED VIEW IF NOT EXISTS station_latest_health AS
SELECT DISTINCT ON (station_pk)
  station_pk,
  observed_at,
  status,
  freshness_minutes,
  sensor_health_json,
  notes
FROM station_health_snapshots
ORDER BY station_pk, observed_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS ux_station_latest_health
  ON station_latest_health (station_pk);

CREATE MATERIALIZED VIEW IF NOT EXISTS station_map_summary AS
SELECT
  s.station_pk,
  s.station_id,
  s.station_num,
  s.name,
  s.device_type,
  s.status,
  s.privacy,
  s.latitude,
  s.longitude,
  s.location_text,
  h.observed_at AS status_observed_at,
  h.freshness_minutes,
  array_remove(array_agg(DISTINCT ml.metric_key), NULL) AS latest_metric_keys
FROM stations s
LEFT JOIN station_latest_health h ON h.station_pk = s.station_pk
LEFT JOIN station_latest_metric_values ml ON ml.station_pk = s.station_pk
GROUP BY s.station_pk, h.observed_at, h.freshness_minutes;

CREATE UNIQUE INDEX IF NOT EXISTS ux_station_map_summary ON station_map_summary (station_pk);

CREATE OR REPLACE FUNCTION refresh_dashboard_views() RETURNS void AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY station_latest_metric_values;
  REFRESH MATERIALIZED VIEW CONCURRENTLY station_latest_health;
  REFRESH MATERIALIZED VIEW CONCURRENTLY station_map_summary;
END;
$$ LANGUAGE plpgsql;

INSERT INTO metric_catalog (metric_key, display_label, canonical_label, unit, category, description)
VALUES
  ('temperature', 'Temperature (°C)', 'Temperature', '°C', 'weather', 'Air temperature from station sensors.'),
  ('humidity', 'Relative Humidity (%)', 'Humidity', '%', 'weather', 'Relative humidity from station sensors.'),
  ('pressure', 'Atmospheric Pressure (hPa)', 'Atmospheric Pressure', 'hPa', 'weather', 'Atmospheric pressure measured by station sensors.'),
  ('co2', 'CO2 (ppm)', 'CO2', 'ppm', 'air_quality', 'Carbon dioxide concentration.'),
  ('pm1', 'PM1 (µg/m³)', 'PM1', 'µg/m³', 'air_quality', 'Particulate matter less than 1 micron.'),
  ('pm2_5', 'PM2.5 (µg/m³)', 'PM2.5', 'µg/m³', 'air_quality', 'Particulate matter less than 2.5 microns.'),
  ('pm10', 'PM10 (µg/m³)', 'PM10', 'µg/m³', 'air_quality', 'Particulate matter less than 10 microns.'),
  ('wind_speed', 'Wind Speed (m/s)', 'Wind Speed', 'm/s', 'weather', 'Wind speed.'),
  ('wind_direction', 'Wind Direction (°)', 'Wind Direction', '°', 'weather', 'Wind direction.'),
  ('radiation', 'Radiation (W/m²)', 'Radiation', 'W/m²', 'weather', 'Solar radiation or irradiance.'),
  ('salinity', 'Salinity (PSU)', 'Salinity', 'PSU', 'marine', 'Practical salinity.'),
  ('oxygen', 'Dissolved Oxygen (µM/L)', 'Oxygen', 'µM/L', 'marine', 'Dissolved oxygen in water.')
ON CONFLICT (metric_key) DO NOTHING;
