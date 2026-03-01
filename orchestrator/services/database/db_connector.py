"""
Database Connector Service

Provides safe, read-only access to PostgreSQL databases for schema introspection
and data quality checks. Implements 3-layer read-only protection.
"""

import asyncio
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Dangerous SQL keywords that should never appear in user/AI queries
DANGEROUS_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|EXECUTE|CALL|DO)\b", re.IGNORECASE
)

MAX_SAMPLE_ROWS = 10
MAX_TOTAL_ROWS = 1000
QUERY_TIMEOUT_SECONDS = 30


class DatabaseConnector:
    """Safe, read-only PostgreSQL connector with connection pooling."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl_mode: str = "prefer",
        schema_name: str = "public",
        is_read_only: bool = True,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.ssl_mode = ssl_mode
        self.schema_name = schema_name
        self.is_read_only = is_read_only
        self._pool = None

    async def connect(self) -> dict[str, Any]:
        """Create connection pool and return server info."""
        import asyncpg

        # Map ssl_mode to asyncpg ssl parameter
        if self.ssl_mode == "disable":
            ssl_arg = False  # Explicitly disable SSL negotiation
        elif self.ssl_mode in ("require", "verify-ca", "verify-full", "allow"):
            ssl_arg = self.ssl_mode
        else:
            ssl_arg = None  # "prefer" or unknown: try default, fall back below
        # For "prefer", try SSL first, fall back to non-SSL
        try:
            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
                ssl=ssl_arg,
                min_size=1,
                max_size=3,
                command_timeout=QUERY_TIMEOUT_SECONDS,
            )
        except Exception:
            if self.ssl_mode == "prefer":
                self._pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.username,
                    password=self.password,
                    ssl=None,
                    min_size=1,
                    max_size=3,
                    command_timeout=QUERY_TIMEOUT_SECONDS,
                )
            else:
                raise

        # Get server info
        async with self._pool.acquire() as conn:
            if self.is_read_only:
                await conn.execute("SET default_transaction_read_only = true")
            version = await conn.fetchval("SELECT version()")
            db_name = await conn.fetchval("SELECT current_database()")
            return {
                "server_version": version,
                "database": db_name,
                "host": self.host,
                "port": self.port,
                "connected": True,
            }

    def _validate_query(self, sql: str) -> None:
        """Layer 3: Keyword validation to reject write operations."""
        # Strip SQL single-line comments before validation
        lines = [line for line in sql.strip().splitlines() if not line.strip().startswith("--")]
        clean_sql = "\n".join(lines).strip()
        if not clean_sql:
            raise ValueError("Query is empty after removing comments")

        if DANGEROUS_KEYWORDS.search(clean_sql):
            raise ValueError(
                f"Query contains dangerous keywords. Only SELECT queries are allowed. "
                f"Detected: {DANGEROUS_KEYWORDS.findall(clean_sql)}"
            )
        # Basic sanity: must start with SELECT, WITH, or EXPLAIN
        stripped = clean_sql.upper()
        if not stripped.startswith(("SELECT", "WITH", "EXPLAIN")):
            raise ValueError("Only SELECT, WITH, or EXPLAIN queries are allowed")

    async def introspect_schema(self) -> dict[str, Any]:
        """Query information_schema for complete schema metadata."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        schema = self.schema_name
        result = {"schema": schema, "tables": [], "foreign_keys": [], "indexes": []}

        async with self._pool.acquire() as conn:
            if self.is_read_only:
                await conn.execute("SET default_transaction_read_only = true")

            # Tables with row count estimates
            tables = await conn.fetch(
                """
                SELECT t.table_name,
                       COALESCE(s.n_live_tup, 0) as estimated_rows,
                       obj_description((quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass, 'pg_class') as table_comment
                FROM information_schema.tables t
                LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name AND s.schemaname = t.table_schema
                WHERE t.table_schema = $1 AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name
            """,
                schema,
            )

            for table in tables:
                table_name = table["table_name"]

                # Columns
                columns = await conn.fetch(
                    """
                    SELECT column_name, data_type, is_nullable, column_default,
                           character_maximum_length, numeric_precision, numeric_scale,
                           col_description((quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass, ordinal_position) as column_comment
                    FROM information_schema.columns
                    WHERE table_schema = $1 AND table_name = $2
                    ORDER BY ordinal_position
                """,
                    schema,
                    table_name,
                )

                # Constraints
                constraints = await conn.fetch(
                    """
                    SELECT tc.constraint_name, tc.constraint_type,
                           kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = $1 AND tc.table_name = $2
                    ORDER BY tc.constraint_type, tc.constraint_name
                """,
                    schema,
                    table_name,
                )

                result["tables"].append(
                    {
                        "table_name": table_name,
                        "estimated_rows": table["estimated_rows"],
                        "comment": table["table_comment"],
                        "columns": [dict(c) for c in columns],
                        "constraints": [dict(c) for c in constraints],
                    }
                )

            # Foreign keys
            fks = await conn.fetch(
                """
                SELECT
                    tc.constraint_name,
                    tc.table_name as from_table,
                    kcu.column_name as from_column,
                    ccu.table_name as to_table,
                    ccu.column_name as to_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = $1 AND tc.constraint_type = 'FOREIGN KEY'
                ORDER BY tc.table_name
            """,
                schema,
            )
            result["foreign_keys"] = [dict(fk) for fk in fks]

            # Indexes
            indexes = await conn.fetch(
                """
                SELECT
                    i.relname as index_name,
                    t.relname as table_name,
                    ix.indisunique as is_unique,
                    ix.indisprimary as is_primary,
                    array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) as columns
                FROM pg_index ix
                JOIN pg_class t ON t.oid = ix.indrelid
                JOIN pg_class i ON i.oid = ix.indexrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                WHERE n.nspname = $1
                GROUP BY i.relname, t.relname, ix.indisunique, ix.indisprimary
                ORDER BY t.relname, i.relname
            """,
                schema,
            )
            result["indexes"] = [dict(idx) for idx in indexes]

        return result

    async def execute_check(self, sql: str) -> dict[str, Any]:
        """Execute a single SELECT query with full safety layers.

        Returns dict with: rows, row_count, sample_data, execution_time_ms
        """
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        # Layer 3: keyword validation
        self._validate_query(sql)

        start = time.monotonic()

        async with self._pool.acquire() as conn:
            # Layer 2: session-level read-only
            if self.is_read_only:
                await conn.execute("SET default_transaction_read_only = true")

            try:
                rows = await asyncio.wait_for(
                    conn.fetch(sql),
                    timeout=QUERY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"Query timed out after {QUERY_TIMEOUT_SECONDS}s")

        elapsed_ms = int((time.monotonic() - start) * 1000)
        total_count = len(rows)

        # Convert to serializable format, limit rows
        sample = []
        for row in rows[:MAX_SAMPLE_ROWS]:
            sample.append({k: _serialize_value(v) for k, v in dict(row).items()})

        return {
            "row_count": min(total_count, MAX_TOTAL_ROWS),
            "total_row_count": total_count,
            "sample_data": sample,
            "execution_time_ms": elapsed_ms,
            "truncated": total_count > MAX_TOTAL_ROWS,
        }

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


def _serialize_value(v: Any) -> Any:
    """Convert asyncpg types to JSON-serializable values."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    # datetime, date, etc
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_serialize_value(i) for i in v]
    return str(v)
