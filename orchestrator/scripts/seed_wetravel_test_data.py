#!/usr/bin/env python3
"""Upsert Wetravel reusable login test data without storing plaintext secrets in Git."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ORCHESTRATOR_DIR.parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PROJECT_ID = "c4b03ab3-8206-4eed-b069-c8b70225de4f"
DEFAULT_EMAIL = "farxad2026@mailinator.com"
DATASET_KEY = "wetravel-auth"
ITEM_KEY = "valid-user"
PASSWORD_ENV = "WETRAVEL_VALID_USER_PASSWORD"


def upsert_wetravel_auth_test_data(
    *, project_id: str, email: str, password: str
) -> dict[str, str]:
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, TestDataItem, TestDataSet
    from orchestrator.services.test_data_resolver import prepare_test_data_item_storage

    now = datetime.utcnow()
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            project = Project(
                id=project_id,
                name="Wetravel",
                description="Wetravel pre-production test project",
            )
            session.add(project)

        dataset = session.exec(
            select(TestDataSet)
            .where(TestDataSet.project_id == project_id)
            .where(TestDataSet.key == DATASET_KEY)
        ).first()
        if dataset:
            dataset.name = "Wetravel Auth"
            dataset.description = "Reusable Wetravel login fixtures"
            dataset.status = "active"
            dataset.format = "json"
            dataset.tags = ["auth", "wetravel"]
            dataset.updated_at = now
        else:
            dataset = TestDataSet(
                project_id=project_id,
                key=DATASET_KEY,
                name="Wetravel Auth",
                description="Reusable Wetravel login fixtures",
                status="active",
                format="json",
                created_at=now,
                updated_at=now,
            )
            dataset.tags = ["auth", "wetravel"]
            session.add(dataset)
            session.flush()

        storage = prepare_test_data_item_storage(
            data={"username": email, "email": email, "password": password},
            sensitive_fields=["password"],
        )
        item = session.exec(
            select(TestDataItem)
            .where(TestDataItem.dataset_id == dataset.id)
            .where(TestDataItem.key == ITEM_KEY)
        ).first()
        if item:
            item.name = "Valid Wetravel user"
            item.description = "Valid Wetravel login account for TC-001"
            item.status = "active"
            item.format = "json"
            item.data = storage["data"]
            item.data_text = storage["text"]
            item.sensitive_fields = storage["sensitive_fields"]
            item.encrypted_values = storage["encrypted_values"]
            item.updated_at = now
        else:
            item = TestDataItem(
                dataset_id=dataset.id,
                key=ITEM_KEY,
                name="Valid Wetravel user",
                description="Valid Wetravel login account for TC-001",
                status="active",
                format="json",
                created_at=now,
                updated_at=now,
                data_text=storage["text"],
            )
            item.data = storage["data"]
            item.sensitive_fields = storage["sensitive_fields"]
            item.encrypted_values = storage["encrypted_values"]
            session.add(item)

        session.commit()
        return {
            "project_id": project_id,
            "dataset": DATASET_KEY,
            "item": ITEM_KEY,
            "ref": f"{DATASET_KEY}.{ITEM_KEY}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Upsert Wetravel auth test data.")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password-env", default=PASSWORD_ENV)
    args = parser.parse_args()

    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit(
            f"Set {args.password_env} for this command; the password is not accepted as a CLI argument."
        )

    from orchestrator.api.db import init_db

    init_db()
    result = upsert_wetravel_auth_test_data(
        project_id=args.project_id, email=args.email, password=password
    )
    print(f"Upserted {result['ref']} for project {result['project_id']}")


if __name__ == "__main__":
    main()
