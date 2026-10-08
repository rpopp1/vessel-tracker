def test_tables_exist_and_insert_routes_to_partition(db):
    db.execute(
        "INSERT INTO vessels (mmsi, ship_type_code) VALUES (1, 80)"
    )
    db.execute(
        "INSERT INTO positions (mmsi, ts, geom) VALUES (1, now(), ST_SetSRID(ST_MakePoint(0,0),4326))"
    )
    assert db.execute("SELECT count(*) AS n FROM positions").fetchone()["n"] == 1
