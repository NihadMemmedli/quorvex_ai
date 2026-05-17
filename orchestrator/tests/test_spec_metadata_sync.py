import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from orchestrator.api.main import sync_spec_metadata_from_file
from orchestrator.api.models_db import SpecMetadata


def _session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_seed_sync_creates_missing_metadata_row(tmp_path):
    metadata_file = tmp_path / "spec-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "example.md": {
                    "tags": ["Browser", " smoke ", "browser", ""],
                    "description": "Seed description",
                    "author": "Seed author",
                    "lastModified": "2026-05-16T12:00:00",
                }
            }
        )
    )

    with _session() as session:
        changed = sync_spec_metadata_from_file(session, metadata_file)
        session.commit()

        meta = session.get(SpecMetadata, "example.md")

    assert changed == 1
    assert meta is not None
    assert meta.tags == ["browser", "smoke"]
    assert meta.description == "Seed description"
    assert meta.author == "Seed author"
    assert meta.last_modified == datetime(2026, 5, 16, 12, 0, 0)


def test_seed_sync_merges_tags_without_overwriting_user_metadata(tmp_path):
    metadata_file = tmp_path / "spec-metadata.json"
    metadata_file.write_text(
        json.dumps(
            {
                "existing.md": {
                    "tags": ["api", "smoke", "Custom"],
                    "description": "Seed description",
                    "author": "Seed author",
                    "lastModified": "2026-05-16T12:00:00",
                }
            }
        )
    )
    user_modified = datetime(2026, 1, 1, 8, 30, 0)

    with _session() as session:
        meta = SpecMetadata(
            spec_name="existing.md",
            description="User description",
            author="User author",
            last_modified=user_modified,
            project_id="project-a",
        )
        meta.tags = ["custom", "API"]
        session.add(meta)
        session.commit()

        changed = sync_spec_metadata_from_file(session, metadata_file)
        session.commit()
        session.refresh(meta)

    assert changed == 1
    assert meta.tags == ["custom", "API", "smoke"]
    assert meta.description == "User description"
    assert meta.author == "User author"
    assert meta.project_id == "project-a"
    assert meta.last_modified == user_modified


def test_checked_in_spec_metadata_covers_all_specs():
    repo_root = Path(__file__).resolve().parents[2]
    specs_dir = repo_root / "specs"
    metadata_file = specs_dir / "spec-metadata.json"

    metadata = json.loads(metadata_file.read_text())
    spec_files = {str(path.relative_to(specs_dir)) for path in specs_dir.glob("**/*.md")}

    assert set(metadata) == spec_files

    for spec_name, entry in metadata.items():
        tags = entry.get("tags")
        assert isinstance(tags, list), spec_name
        assert tags, spec_name
        assert all(isinstance(tag, str) for tag in tags), spec_name
        assert all(tag == tag.strip() and tag == tag.lower() for tag in tags), spec_name
        assert len(tags) == len({tag.casefold() for tag in tags}), spec_name
