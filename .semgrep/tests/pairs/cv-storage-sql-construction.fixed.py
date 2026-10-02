async def f(conn, sym):
    await conn.execute("SELECT * FROM t WHERE s = $1", sym)
