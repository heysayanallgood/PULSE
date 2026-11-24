import duckdb
con = duckdb.connect('data/database/gtfs.duckdb', read_only=True)
res = con.execute("SELECT route_id, route_short_name, route_long_name FROM routes WHERE route_short_name ILIKE '%425%' LIMIT 5;").fetchall()
print("Matches:", res)
if res:
    rid = res[0][0]
    st = con.execute(f"SELECT st.stop_sequence, s.stop_name, st.stop_dist FROM stop_times st JOIN stops s ON st.stop_id=s.stop_id JOIN trips t ON st.trip_id=t.trip_id WHERE t.route_id='{rid}' LIMIT 10;").fetchall()
    print("Stop times sample:", st)
