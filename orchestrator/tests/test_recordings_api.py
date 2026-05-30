from pathlib import Path

from services.recording_codegen import build_codegen_command, has_usable_codegen_output, read_codegen_failure


def test_codegen_device_takes_precedence_over_viewport():
    command = build_codegen_command(
        "https://example.com/login",
        Path("/tmp/recording.spec.ts"),
        {"device": "iPhone 13", "viewport_size": "1280,720"},
    )

    assert command == [
        "npx",
        "playwright",
        "codegen",
        "--target",
        "playwright-test",
        "--output",
        "/tmp/recording.spec.ts",
        "--device",
        "iPhone 13",
        "https://example.com/login",
    ]


def test_codegen_viewport_used_without_device():
    command = build_codegen_command(
        "https://example.com/login",
        Path("/tmp/recording.spec.ts"),
        {"viewport_size": "1280,720"},
    )

    assert "--viewport-size" in command
    assert "--device" not in command


def test_about_blank_only_codegen_output_is_not_usable(tmp_path):
    code_path = tmp_path / "recording.spec.ts"
    code_path.write_text(
        """
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('about:blank');
});
""",
        encoding="utf-8",
    )

    assert has_usable_codegen_output(code_path) is False


def test_meaningful_codegen_output_is_usable_even_after_nonzero_exit(tmp_path):
    code_path = tmp_path / "recording.spec.ts"
    code_path.write_text(
        """
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('https://example.com/login');
});
""",
        encoding="utf-8",
    )

    assert has_usable_codegen_output(code_path) is True


def test_codegen_failure_reads_stderr(tmp_path):
    code_path = tmp_path / "recording.spec.ts"
    (tmp_path / "codegen.err.log").write_text("Unspecified proxy lookup failure\n", encoding="utf-8")

    assert read_codegen_failure(code_path) == "Unspecified proxy lookup failure"
