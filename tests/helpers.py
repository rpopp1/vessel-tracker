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
