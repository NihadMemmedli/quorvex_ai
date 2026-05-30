import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.native_api_healer import NativeApiHealer


def test_api_healer_prompt_includes_structured_failure_context():
    prompt = NativeApiHealer()._build_healer_prompt(
        test_file="tests/generated/api.spec.ts",
        test_content="import { test } from '@playwright/test';\ntest('api', async () => {});",
        error_log="raw error",
        spec_content="# API Spec",
        failure_context="## Structured Failure Context\nPlaywright JSON summary: failed",
    )

    assert "## Structured Failure Context" in prompt
    assert "Playwright JSON summary: failed" in prompt
