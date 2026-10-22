def test_seed_loads_the_example_participants(conn):
    rows = conn.execute("SELECT id FROM participant ORDER BY id").fetchall()

    assert [row[0] for row in rows] == ["lotti", "luis", "seph", "vini", "vitor"]
