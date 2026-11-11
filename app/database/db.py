"""
Voxlyne - Database Connection
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
    from pathlib import Path
    from typing import List

    def _split_sql_statements(sql: str) -> List[str]:
        """
        Split SQL into statements, honoring quoted strings, comments and dollar-quoted blocks.
        """
        statements: List[str] = []
        buf: list[str] = []
        i = 0
        in_single = False
        in_double = False
        in_dollar: str | None = None
        in_block_comment = False

        while i < len(sql):
            ch = sql[i]
            nxt = sql[i + 1] if i + 1 < len(sql) else ""

            if in_dollar:
                if sql.startswith(in_dollar, i):
                    buf.append(in_dollar)
                    i += len(in_dollar)
                    in_dollar = None
                    continue
                buf.append(ch)
                i += 1
                continue

            if in_block_comment:
                if ch == "*" and nxt == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue

            # Skip line comments and block comments outside strings.
            if ch == "-" and nxt == "-":
                i += 2
                while i < len(sql) and sql[i] not in ("\n", "\r"):
                    i += 1
                continue

            if ch == "/" and nxt == "*":
                in_block_comment = True
                i += 2
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
        sql = migration_file.read_text()
        # Split statements while honoring quoted blocks/comments.
        statements = _split_sql_statements(sql)
        skipped_idempotent = 0

        for idx, statement in enumerate(statements, start=1):
            if not statement:
                continue
            try:
                await db.execute(statement)
            except Exception as e:
                # Continue only on idempotent errors and keep running the rest.
                error_msg = str(e).lower()
                if "already exists" in error_msg or "duplicate" in error_msg:
                    skipped_idempotent += 1
                    logger.debug(
                        "Skipping idempotent statement in %s [%s/%s]: %s",
                        migration_file.name,
                        idx,
                        len(statements),
                        e,
                    )
                    continue
                logger.error(
                    "Migration failed: %s [%s/%s] - %s",
                    migration_file.name,
                    idx,
                    len(statements),
                    e,
                )
                raise

        if skipped_idempotent:
            logger.info(
                "Migration completed with %s idempotent skips: %s",
                skipped_idempotent,
                migration_file.name,
            )
        else:
            logger.info(f"Migration completed: {migration_file.name}")
