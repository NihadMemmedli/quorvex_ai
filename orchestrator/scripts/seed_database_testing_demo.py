#!/usr/bin/env python3
"""
Seed deterministic Database Testing demo content.

The command creates an isolated PostgreSQL schema with sample commerce data,
then upserts platform metadata so the Database Testing page has a connection,
spec, historical run, and check results ready for demos.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session, select

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ORCHESTRATOR_DIR.parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from api.credentials import encrypt_credential
from api.database_testing import _get_specs_dir
from api.db import DATABASE_URL, engine, get_database_type, init_db
from api.models_db import DbConnection, DbTestCheck, DbTestRun, Project

DEMO_SCHEMA = "quorvex_demo"
DEMO_CONNECTION_ID = "dbc-demo-shop"
DEMO_RUN_ID = "dbt-demo-quality"
DEMO_SPEC_NAME = "demo-shop-quality.md"
DEMO_CONNECTION_NAME = "Quorvex Demo Shop"


@dataclass(frozen=True)
class ConnectionProfile:
    host: str
    port: int
    database: str
    username: str
    password: str


def connection_profile_from_url(
    database_url: str,
    *,
    override_host: str | None = None,
    override_port: int | None = None,
) -> ConnectionProfile:
    """Build the connection profile that the backend will use for demo checks."""
    url = make_url(database_url)
    return ConnectionProfile(
        host=override_host or url.host or "localhost",
        port=override_port or url.port or 5432,
        database=url.database or "playwright_agent",
        username=url.username or "postgres",
        password=url.password or "",
    )


def ensure_demo_schema(schema_name: str = DEMO_SCHEMA) -> None:
    """Reset and seed the isolated PostgreSQL demo schema."""
    if get_database_type() != "postgresql":
        raise RuntimeError("Database Testing demo seed requires PostgreSQL. Start the dev database first.")

    schema = _quote_ident(schema_name)
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(_demo_schema_sql(schema)))


def ensure_demo_platform_data(
    *,
    project_id: str,
    profile: ConnectionProfile,
    schema_name: str = DEMO_SCHEMA,
) -> dict:
    """Upsert the connection, spec, run, and check rows used by the UI demo."""
    spec_path = ensure_demo_spec(project_id=project_id, schema_name=schema_name)
    now = datetime.utcnow()

    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            project = Project(
                id=project_id,
                name="Default Project" if project_id == "default" else f"Database Demo {project_id}",
                description="Project seeded for Database Testing demos",
            )
            session.add(project)

        existing_connection = session.get(DbConnection, DEMO_CONNECTION_ID)
        if existing_connection:
            existing_connection.project_id = project_id
            existing_connection.name = DEMO_CONNECTION_NAME
            existing_connection.host = profile.host
            existing_connection.port = profile.port
            existing_connection.database = profile.database
            existing_connection.username = profile.username
            existing_connection.password_encrypted = encrypt_credential(profile.password)
            existing_connection.ssl_mode = "disable"
            existing_connection.schema_name = schema_name
            existing_connection.is_read_only = True
            existing_connection.last_tested_at = now
            existing_connection.last_test_success = True
            existing_connection.last_test_error = None
            existing_connection.updated_at = now
            connection = existing_connection
        else:
            connection = DbConnection(
                id=DEMO_CONNECTION_ID,
                project_id=project_id,
                name=DEMO_CONNECTION_NAME,
                host=profile.host,
                port=profile.port,
                database=profile.database,
                username=profile.username,
                password_encrypted=encrypt_credential(profile.password),
                ssl_mode="disable",
                schema_name=schema_name,
                is_read_only=True,
                last_tested_at=now,
                last_test_success=True,
                created_at=now - timedelta(days=2),
                updated_at=now,
            )
            session.add(connection)

        existing_checks = session.exec(select(DbTestCheck).where(DbTestCheck.run_id == DEMO_RUN_ID)).all()
        for check in existing_checks:
            session.delete(check)

        existing_run = session.get(DbTestRun, DEMO_RUN_ID)
        if existing_run:
            session.delete(existing_run)
            session.flush()

        run = DbTestRun(
            id=DEMO_RUN_ID,
            connection_id=DEMO_CONNECTION_ID,
            project_id=project_id,
            spec_name=DEMO_SPEC_NAME,
            run_type="data_quality",
            status="completed",
            current_stage="done",
            stage_message="Completed: 4 passed, 4 failed, 0 errors",
            total_checks=8,
            passed_checks=4,
            failed_checks=4,
            error_checks=0,
            critical_count=1,
            high_count=2,
            medium_count=1,
            low_count=0,
            info_count=0,
            ai_summary=(
                "Demo shop data has strong baseline integrity, but checkout readiness is reduced by duplicate "
                "customers, invalid email addresses, negative item quantities, and stale support tickets."
            ),
            created_at=now - timedelta(hours=6),
            started_at=now - timedelta(hours=6, seconds=-2),
            completed_at=now - timedelta(hours=6, seconds=-9),
        )
        session.add(run)
        session.flush()

        for check in _demo_check_rows(project_id):
            session.add(check)

        session.commit()

    return {
        "project_id": project_id,
        "connection_id": DEMO_CONNECTION_ID,
        "connection_name": DEMO_CONNECTION_NAME,
        "schema": schema_name,
        "spec": str(spec_path.relative_to(PROJECT_ROOT)),
        "run_id": DEMO_RUN_ID,
    }


def ensure_demo_spec(*, project_id: str, schema_name: str = DEMO_SCHEMA) -> Path:
    specs_dir = _get_specs_dir(project_id)
    target = specs_dir / DEMO_SPEC_NAME
    target.write_text(_demo_spec_content(schema_name), encoding="utf-8")
    return target


def _demo_check_rows(project_id: str) -> list[DbTestCheck]:
    checks = [
        {
            "check_name": "customers_email_present",
            "check_type": "null_check",
            "table_name": "customers",
            "column_name": "email",
            "severity": "critical",
            "status": "passed",
            "row_count": 0,
            "execution_time_ms": 18,
            "sample_data": [],
            "sql_query": "SELECT id, full_name FROM customers WHERE email IS NULL LIMIT 100",
        },
        {
            "check_name": "customers_email_format",
            "check_type": "pattern",
            "table_name": "customers",
            "column_name": "email",
            "severity": "high",
            "status": "failed",
            "row_count": 1,
            "execution_time_ms": 22,
            "sample_data": [{"id": 4, "email": "invalid-email", "full_name": "Dana Fields"}],
            "sql_query": (
                "SELECT id, email, full_name FROM customers "
                "WHERE email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}$' LIMIT 100"
            ),
        },
        {
            "check_name": "customers_unique_email",
            "check_type": "uniqueness",
            "table_name": "customers",
            "column_name": "email",
            "severity": "high",
            "status": "failed",
            "row_count": 1,
            "execution_time_ms": 25,
            "sample_data": [{"email": "alex@example.com", "duplicate_count": 2}],
            "sql_query": (
                "SELECT email, COUNT(*) AS duplicate_count FROM customers "
                "GROUP BY email HAVING COUNT(*) > 1 LIMIT 100"
            ),
        },
        {
            "check_name": "orders_total_non_negative",
            "check_type": "range",
            "table_name": "orders",
            "column_name": "total_amount",
            "severity": "high",
            "status": "passed",
            "row_count": 0,
            "execution_time_ms": 17,
            "sample_data": [],
            "sql_query": "SELECT id, total_amount FROM orders WHERE total_amount < 0 LIMIT 100",
        },
        {
            "check_name": "order_items_quantity_positive",
            "check_type": "range",
            "table_name": "order_items",
            "column_name": "quantity",
            "severity": "critical",
            "status": "failed",
            "row_count": 1,
            "execution_time_ms": 19,
            "sample_data": [{"id": 6, "order_id": 5, "product_id": 4, "quantity": -1}],
            "sql_query": "SELECT id, order_id, product_id, quantity FROM order_items WHERE quantity <= 0 LIMIT 100",
        },
        {
            "check_name": "payments_match_order_total",
            "check_type": "custom",
            "table_name": "payments",
            "column_name": "amount",
            "severity": "medium",
            "status": "failed",
            "row_count": 1,
            "execution_time_ms": 31,
            "sample_data": [{"order_id": 4, "order_total": "149.00", "paid_total": "99.00"}],
            "sql_query": (
                "SELECT o.id AS order_id, o.total_amount AS order_total, COALESCE(SUM(p.amount), 0) AS paid_total "
                "FROM orders o LEFT JOIN payments p ON p.order_id = o.id "
                "WHERE o.status IN ('paid', 'shipped') "
                "GROUP BY o.id, o.total_amount HAVING COALESCE(SUM(p.amount), 0) <> o.total_amount LIMIT 100"
            ),
        },
        {
            "check_name": "open_tickets_recent_activity",
            "check_type": "freshness",
            "table_name": "support_tickets",
            "column_name": "updated_at",
            "severity": "medium",
            "status": "passed",
            "row_count": 0,
            "execution_time_ms": 15,
            "sample_data": [],
            "sql_query": (
                "SELECT id, subject, updated_at FROM support_tickets "
                "WHERE status = 'open' AND updated_at < NOW() - INTERVAL '14 days' LIMIT 100"
            ),
        },
        {
            "check_name": "products_have_sku",
            "check_type": "null_check",
            "table_name": "products",
            "column_name": "sku",
            "severity": "medium",
            "status": "passed",
            "row_count": 0,
            "execution_time_ms": 14,
            "sample_data": [],
            "sql_query": "SELECT id, name FROM products WHERE sku IS NULL OR sku = '' LIMIT 100",
        },
    ]

    rows: list[DbTestCheck] = []
    for check in checks:
        sample = check.pop("sample_data")
        rows.append(
            DbTestCheck(
                run_id=DEMO_RUN_ID,
                project_id=project_id,
                description=f"Demo check: {check['check_name'].replace('_', ' ')}",
                expected_result="0 rows",
                actual_result=json.dumps(sample[:3]) if sample else "[]",
                sample_data_json=json.dumps(sample),
                **check,
            )
        )
    return rows


def _demo_spec_content(schema_name: str) -> str:
    return f"""# Database Quality Checks: Demo Shop

Runnable SELECT-only checks for the Quorvex Demo Shop schema.

```sql
-- check: customers_email_present | null_check | critical
SELECT id, full_name
FROM {schema_name}.customers
WHERE email IS NULL
LIMIT 100
```

```sql
-- check: customers_email_format | pattern | high
SELECT id, email, full_name
FROM {schema_name}.customers
WHERE email !~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{{2,}}$'
LIMIT 100
```

```sql
-- check: customers_unique_email | uniqueness | high
SELECT email, COUNT(*) AS duplicate_count
FROM {schema_name}.customers
GROUP BY email
HAVING COUNT(*) > 1
LIMIT 100
```

```sql
-- check: order_items_quantity_positive | range | critical
SELECT id, order_id, product_id, quantity
FROM {schema_name}.order_items
WHERE quantity <= 0
LIMIT 100
```

```sql
-- check: payments_match_order_total | custom | medium
SELECT o.id AS order_id, o.total_amount AS order_total, COALESCE(SUM(p.amount), 0) AS paid_total
FROM {schema_name}.orders o
LEFT JOIN {schema_name}.payments p ON p.order_id = o.id
WHERE o.status IN ('paid', 'shipped')
GROUP BY o.id, o.total_amount
HAVING COALESCE(SUM(p.amount), 0) <> o.total_amount
LIMIT 100
```
"""


def _demo_schema_sql(schema: str) -> str:
    return f"""
CREATE TABLE {schema}.customers (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    full_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE {schema}.products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE {schema}.orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id),
    status TEXT NOT NULL,
    total_amount NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE {schema}.order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES {schema}.orders(id),
    product_id INTEGER NOT NULL REFERENCES {schema}.products(id),
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL
);

CREATE TABLE {schema}.payments (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES {schema}.orders(id),
    amount NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL,
    paid_at TIMESTAMPTZ
);

CREATE TABLE {schema}.support_tickets (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES {schema}.customers(id),
    subject TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

INSERT INTO {schema}.customers (id, email, full_name, status, created_at) VALUES
    (1, 'alex@example.com', 'Alex Morgan', 'active', NOW() - INTERVAL '80 days'),
    (2, 'sam@example.com', 'Sam Rivera', 'active', NOW() - INTERVAL '45 days'),
    (3, 'alex@example.com', 'Alex Morgan Duplicate', 'active', NOW() - INTERVAL '20 days'),
    (4, 'invalid-email', 'Dana Fields', 'active', NOW() - INTERVAL '12 days'),
    (5, 'lee@example.com', 'Lee Chen', 'inactive', NOW() - INTERVAL '180 days');

INSERT INTO {schema}.products (id, sku, name, category, price, is_active) VALUES
    (1, 'QX-PLAN-PRO', 'Pro Plan', 'subscription', 49.00, true),
    (2, 'QX-PLAN-ENT', 'Enterprise Plan', 'subscription', 249.00, true),
    (3, 'QX-AUDIT', 'Audit Add-on', 'service', 99.00, true),
    (4, 'QX-LEGACY', 'Legacy Connector', 'integration', 149.00, false);

INSERT INTO {schema}.orders (id, customer_id, status, total_amount, created_at) VALUES
    (1, 1, 'paid', 49.00, NOW() - INTERVAL '15 days'),
    (2, 2, 'shipped', 348.00, NOW() - INTERVAL '9 days'),
    (3, 3, 'draft', 0.00, NOW() - INTERVAL '4 days'),
    (4, 4, 'paid', 149.00, NOW() - INTERVAL '2 days'),
    (5, 5, 'paid', 99.00, NOW() - INTERVAL '1 day');

INSERT INTO {schema}.order_items (id, order_id, product_id, quantity, unit_price) VALUES
    (1, 1, 1, 1, 49.00),
    (2, 2, 2, 1, 249.00),
    (3, 2, 3, 1, 99.00),
    (4, 4, 4, 1, 149.00),
    (5, 5, 3, 1, 99.00),
    (6, 5, 4, -1, 149.00);

INSERT INTO {schema}.payments (id, order_id, amount, status, paid_at) VALUES
    (1, 1, 49.00, 'captured', NOW() - INTERVAL '15 days'),
    (2, 2, 348.00, 'captured', NOW() - INTERVAL '9 days'),
    (3, 4, 99.00, 'captured', NOW() - INTERVAL '2 days'),
    (4, 5, 99.00, 'captured', NOW() - INTERVAL '1 day');

INSERT INTO {schema}.support_tickets (id, customer_id, subject, status, updated_at) VALUES
    (1, 1, 'Invoice copy needed', 'closed', NOW() - INTERVAL '12 days'),
    (2, 2, 'Enterprise onboarding question', 'open', NOW() - INTERVAL '3 days'),
    (3, 4, 'Payment receipt mismatch', 'open', NOW() - INTERVAL '2 days');
"""


def _quote_ident(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum() or identifier[0].isdigit():
        raise ValueError(f"Unsafe SQL identifier: {identifier}")
    return f'"{identifier}"'


def seed_database_testing_demo(
    *,
    project_id: str = "default",
    schema_name: str = DEMO_SCHEMA,
    connection_host: str | None = None,
    connection_port: int | None = None,
) -> dict:
    init_db()
    profile = connection_profile_from_url(
        DATABASE_URL,
        override_host=connection_host,
        override_port=connection_port,
    )
    ensure_demo_schema(schema_name)
    return ensure_demo_platform_data(project_id=project_id, profile=profile, schema_name=schema_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Database Testing demo content")
    parser.add_argument("--project-id", default="default", help="Project ID to seed")
    parser.add_argument("--schema", default=DEMO_SCHEMA, help="PostgreSQL schema to reset and seed")
    parser.add_argument("--connection-host", default=None, help="Override host stored in the demo connection")
    parser.add_argument("--connection-port", type=int, default=None, help="Override port stored in the demo connection")
    args = parser.parse_args()

    result = seed_database_testing_demo(
        project_id=args.project_id,
        schema_name=args.schema,
        connection_host=args.connection_host,
        connection_port=args.connection_port,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
