import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.full_native_pipeline import FullNativePipeline
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
    assert "Do not weaken or delete assertions" in prompt


def test_api_healer_guardrail_rejects_assertion_removal():
    pipeline = object.__new__(FullNativePipeline)
    before = "import { test, expect } from '@playwright/test';\ntest('api', async ({ request }) => { expect(200).toBe(201); });"
    after = "import { test, expect } from '@playwright/test';\ntest('api', async ({ request }) => { const response = await request.get('/x'); });"

    result = pipeline._evaluate_api_healer_guardrails(
        content_before=before,
        content_after=after,
    )

    assert result["guardrail_status"] == "failed"
    assert "assertion_or_explicit_test_fixme" in result["missing_required_tools"]
    assert "assertion_preservation_or_explicit_test_fixme" in result["missing_required_tools"]
