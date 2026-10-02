"""Fixtures for cv-storage-sql-construction (E07-X02, SR-097 neighbourhood)."""
from sqlalchemy import text


async def bad(conn, sym, parts):
    await conn.execute(f"SELECT * FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction
    await conn.execute("SELECT * FROM t WHERE s = '%s'" % sym)  # ruleid: cv-storage-sql-construction
    await conn.fetch("SELECT * FROM t WHERE s = '" + sym + "'")  # ruleid: cv-storage-sql-construction
    return text(f"DELETE FROM t WHERE s = '{sym}'")  # ruleid: cv-storage-sql-construction


async def good(conn, sym):
    await conn.execute("SELECT * FROM t WHERE s = $1", sym)  # ok: cv-storage-sql-construction
    return text("SELECT 1 WHERE s = :s")  # ok: cv-storage-sql-construction
