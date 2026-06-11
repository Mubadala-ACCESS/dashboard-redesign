/*
  MongoDB performance indexes for the legacy/current ACCESS database.
  Run with:
    mongosh mongodb://HOST:27017/all_stations_db database/mongodb_indexes.js
*/

const dbName = db.getName();
print(`Applying performance indexes to ${dbName}...`);

// Station discovery map and filters
print('Indexing stations_info...');
db.stations_info.createIndex({ id: 1 }, { unique: true, sparse: true, name: 'ux_station_id' });
db.stations_info.createIndex({ station_num: 1 }, { unique: true, sparse: true, name: 'ux_station_num' });
db.stations_info.createIndex({ type: 1, status: 1, public: 1 }, { name: 'ix_station_filters' });
db.stations_info.createIndex({ name: 1 }, { name: 'ix_station_name' });
db.stations_info.createIndex({ public: 1, status: 1 }, { name: 'ix_station_public_status' });
db.stations_info.createIndex({ lat: 1, long: 1 }, { name: 'ix_station_coordinates' });

db.stations_info.createIndex(
  { name: 'text', id: 'text' },
  {
    name: 'tx_station_lookup',
    default_language: 'english',
    weights: { name: 10, id: 5 },
  }
);

// Special collections already called directly by the legacy app and the new FastAPI adapter
print('Indexing special collections...');
db.buoy_01.createIndex({ datetime: -1 }, { name: 'ix_buoy_datetime_desc' });
db.buoy_samples.createIndex({ ts: -1 }, { name: 'ix_spotter_ts_desc' });
db.buoy_samples.createIndex({ timestamp: -1 }, { name: 'ix_spotter_timestamp_desc', sparse: true });
db.buoy_samples.createIndex({ 'meta.station_id': 1, ts: -1 }, { name: 'ix_spotter_meta_station_ts' });
db.buoy_samples.createIndex({ 'meta.spotter_id': 1, ts: -1 }, { name: 'ix_spotter_meta_spotter_ts' });
db.buoy_samples.createIndex({ station_id: 1, ts: -1 }, { name: 'ix_spotter_station_ts', sparse: true });
db.buoy_samples.createIndex({ spotter_id: 1, ts: -1 }, { name: 'ix_spotter_spotter_ts', sparse: true });
db.buoy_samples.createIndex({ station_name: 1, ts: -1 }, { name: 'ix_spotter_station_name_ts', sparse: true });
db.f1_meteostation.createIndex({ Timestamp: -1 }, { name: 'ix_meteo_timestamp_desc' });
db.fidas_nyuad.createIndex({ datetime: -1 }, { name: 'ix_fidas_datetime_desc' });

// Per-station realtime collections. This walks station collections and ensures the main time index exists.
print('Indexing per-station collections...');
db.getCollectionNames()
  .filter((name) => /^station\d+$/.test(name))
  .forEach((name) => {
    db.getCollection(name).createIndex({ datetime: -1 }, { name: 'ix_station_datetime_desc' });
    db.getCollection(name).createIndex({ datetime: 1 }, { name: 'ix_station_datetime_asc' });
  });

print('Done.');
