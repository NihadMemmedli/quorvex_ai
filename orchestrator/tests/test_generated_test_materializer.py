from pathlib import Path

from orchestrator.utils.generated_test_materializer import materialize_generated_test_for_run


def test_materializes_absolute_older_run_test_into_active_run(tmp_path: Path):
    old_run_test = tmp_path / "runs" / "old" / "tests" / "generated" / "checkout.spec.ts"
    old_run_test.parent.mkdir(parents=True)
    old_run_test.write_text("import { test } from '@playwright/test';\n")
    run_dir = tmp_path / "runs" / "new"

    result = materialize_generated_test_for_run(old_run_test, run_dir)

    assert result.test_file_path == run_dir.resolve() / "tests" / "generated" / "checkout.spec.ts"
    assert result.test_file_path.read_text() == old_run_test.read_text()
    assert result.source_test_file_path == old_run_test.resolve()


def test_materializes_relative_repo_test_into_active_run(tmp_path: Path):
    source = tmp_path / "tests" / "generated" / "login.spec.ts"
    source.parent.mkdir(parents=True)
    source.write_text("test('login', async () => {});\n")
    run_dir = tmp_path / "runs" / "active"

    result = materialize_generated_test_for_run("tests/generated/login.spec.ts", run_dir, base_dir=tmp_path)

    assert result.test_file_path == run_dir.resolve() / "tests" / "generated" / "login.spec.ts"
    assert result.test_file_path.read_text() == source.read_text()
    assert result.source_test_file_path == source.resolve()


def test_materialization_does_not_modify_source_file(tmp_path: Path):
    source = tmp_path / "runs" / "old" / "tests" / "generated" / "profile.spec.ts"
    source.parent.mkdir(parents=True)
    original = "test('profile', async () => {});\n"
    source.write_text(original)
    run_dir = tmp_path / "runs" / "active"

    result = materialize_generated_test_for_run(source, run_dir)
    result.test_file_path.write_text("test('healed copy', async () => {});\n")

    assert source.read_text() == original
    assert result.test_file_path.read_text() != source.read_text()
