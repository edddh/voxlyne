"""
Ascolta - Database Connection
Async PostgreSQL connection using databases library
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from databases import Database

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global database instance
_database: Optional[Database] = None


def get_database() -> Database:
    """Get the database instance."""
    global _database
    if _database is None:
        settings = get_settings()
        _database = Database(settings.database_url)
    return _database


async def connect_database() -> None:
    """Connect to the database."""
    db = get_database()
    if not db.is_connected:
        logger.info("Connecting to database...")
        await db.connect()
        logger.info("Database connected successfully")


async def disconnect_database() -> None:
    """Disconnect from the database."""
    db = get_database()
    if db.is_connected:
        logger.info("Disconnecting from database...")
        await db.disconnect()
        logger.info("Database disconnected")


async def check_database_health() -> bool:
    """Check if database connection is healthy."""
    try:
        db = get_database()
        if not db.is_connected:
            return False
        # Execute a simple query to verify connection
        await db.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[Database, None]:
    """
    Context manager for database operations.
    Ensures proper connection handling.
    """
    db = get_database()
    if not db.is_connected:
        await db.connect()
    try:
        yield db
    finally:
        # Note: We don't disconnect here as we're using a connection pool
        pass


async def run_migrations() -> None:
    """
    Run database migrations on startup.
    In production, you might want to use Alembic instead.
    """
    import os
    from pathlib import Path
    from typing import List

    def _split_sql_statements(sql: str) -> List[str]:
        """
        Split SQL into statements, honoring quoted strings and dollar-quoted blocks.
        """
        statements: List[str] = []
        buf: list[str] = []
        i = 0
        in_single = False
        in_double = False
        in_dollar: str | None = None

        while i < len(sql):
            ch = sql[i]

            if in_dollar:
                if sql.startswith(in_dollar, i):
                    buf.append(in_dollar)
                    i += len(in_dollar)
                    in_dollar = None
                    continue
                buf.append(ch)
                i += 1
                continue

            if in_single:
                buf.append(ch)
                if ch == "'" and (i == 0 or sql[i - 1] != "\\"):
                    in_single = False
                i += 1
                continue

            if in_double:
                buf.append(ch)
                if ch == '"' and (i == 0 or sql[i - 1] != "\\"):
                    in_double = False
                i += 1
                continue

            if ch == "'":
                in_single = True
                buf.append(ch)
                i += 1
                continue

            if ch == '"':
                in_double = True
                buf.append(ch)
                i += 1
                continue

            if ch == "$":
                j = i + 1
                while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                    j += 1
                if j < len(sql) and sql[j] == "$":
                    in_dollar = sql[i : j + 1]
                    buf.append(in_dollar)
                    i = j + 1
                    continue

            if ch == ";":
                statement = "".join(buf).strip()
                if statement:
                    statements.append(statement)
                buf = []
                i += 1
                continue

            buf.append(ch)
            i += 1

        tail = "".join(buf).strip()
        if tail:
            statements.append(tail)

        return statements

    db = get_database()
    migrations_dir = Path(__file__).parent.parent.parent / "migrations"

    if not migrations_dir.exists():
        logger.warning(f"Migrations directory not found: {migrations_dir}")
        return

    # Get all SQL files sorted by name
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration_file in migration_files:
        logger.info(f"Running migration: {migration_file.name}")
        try:
            sql = migration_file.read_text()
            # Split statements while honoring dollar-quoted blocks
            statements = _split_sql_statements(sql)
            for statement in statements:
                if statement:
                    await db.execute(statement)
            logger.info(f"Migration completed: {migration_file.name}")
        except Exception as e:
            # Check if it's a "already exists" error (idempotent migrations)
            error_msg = str(e).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                logger.info(f"Migration already applied: {migration_file.name}")
            else:
                logger.error(f"Migration failed: {migration_file.name} - {e}")
                raise
