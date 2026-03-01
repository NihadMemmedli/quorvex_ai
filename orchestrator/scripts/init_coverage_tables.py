"""
Migration script to create Phase 1 coverage tables.

Run with: python -m orchestrator.scripts.init_coverage_tables
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from orchestrator.api.models_db import (
    SQLModel,
)


def create_tables(database_url: str = "postgresql://postgres:postgres@localhost:5434/testdb"):
    """
    Create the new coverage tables.

    Args:
        database_url: PostgreSQL connection URL
    """
    print(f"Connecting to database: {database_url}")

    engine = create_engine(database_url)

    print("Creating coverage tables...")

    # Create all tables
    SQLModel.metadata.create_all(engine)

    # Verify tables were created
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN (
                'coverage_metrics',
                'discovered_elements',
                'test_patterns',
                'coverage_gaps',
                'application_map',
                'projects'
            )
            ORDER BY tablename;
        """)
        )

        tables = [row[0] for row in result]
        print(f"\nCreated/verified tables: {tables}")

    print("\n✅ Coverage tables created successfully!")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Create coverage tables")
    parser.add_argument(
        "--db-url", default="postgresql://postgres:postgres@localhost:5434/testdb", help="PostgreSQL connection URL"
    )

    args = parser.parse_args()

    try:
        create_tables(args.db_url)
    except Exception as e:
        print(f"\n❌ Error creating tables: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
