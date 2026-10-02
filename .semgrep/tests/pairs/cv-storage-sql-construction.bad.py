async def f(conn, sym):
    await conn.execute(f"SELECT * FROM t WHERE s = '{sym}'")
