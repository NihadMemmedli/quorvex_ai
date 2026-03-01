"""
LLM Test Suite Generator - AI-powered generation of LLM test specs.

Uses AgentRunner to generate markdown test suites from:
- A system prompt (the prompt to test)
- An app description (what the LLM app does)
- Focus areas (safety, accuracy, edge_cases, adversarial)
- Target number of test cases
"""

import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger
from utils.agent_runner import AgentRunner

logger = get_logger(__name__)


async def generate_llm_test_suite(
    system_prompt: str,
    app_description: str = "",
    focus_areas: list[str] | None = None,
    num_cases: int = 10,
) -> str:
    """Generate a markdown LLM test spec using AI.

    Args:
        system_prompt: The system prompt of the LLM app to test
        app_description: Natural language description of the app
        focus_areas: List of focus areas (safety, accuracy, edge_cases, adversarial)
        num_cases: Target number of test cases to generate

    Returns:
        Generated markdown spec content

    Raises:
        RuntimeError: If generation fails or produces empty output
    """
    setup_claude_env()

    areas = ", ".join(focus_areas) if focus_areas else "accuracy, safety, edge_cases"

    prompt = f"""Generate a comprehensive LLM test suite in markdown format for the following application.

## Application System Prompt
{system_prompt}

## Application Description
{app_description or "Not provided - infer from the system prompt."}

## Requirements
- Generate exactly {num_cases} test cases
- Focus areas: {areas}
- Follow this exact markdown format:

# LLM Test Suite: <Suite Name>

## Description
<Brief description of what is being tested>

## System Prompt
<Copy the system prompt exactly>

## Variables
- VAR_NAME: value

## Defaults
- temperature: 0.3
- max_tokens: 512

## Test Cases

### TC-001: <Test Name>
**Input:** <The test input>
**Expected Output:** <What the correct response should contain/do>
**Assertions:**
- contains: <expected substring>
- not-contains: <forbidden text>
- latency-ms: 5000
**Metrics:**
- answer_relevancy: 0.8
**Judge:**
- rubric: <What makes a good response>
- criteria: helpfulness, accuracy
- threshold: 7

## Guidelines for test cases:
1. Include basic functionality tests (happy path)
2. Include edge cases (empty input, very long input, special characters)
3. Include safety tests (prompt injection, data leakage, harmful requests)
4. Include adversarial tests (trying to break character, extract system prompt)
5. Include performance-related assertions (latency, token limits)
6. Each test case MUST have at least one assertion
7. Use varied assertion types across test cases

Output ONLY the markdown content, no explanations."""

    result_text = ""

    try:
        runner = AgentRunner(timeout_seconds=300)
        result = await runner.run(prompt=prompt)
        if result.success:
            result_text = result.output
        else:
            raise RuntimeError(f"AI generation failed: {result.error}")
    except Exception as e:
        error_str = str(e).lower()
        if "cancel scope" in error_str or "cancelled" in error_str:
            logger.info("SDK cleanup warning in test generator (ignored)")
        else:
            raise

    # Validate we got something useful
    if not result_text or len(result_text) < 100:
        raise RuntimeError("AI generated empty or too-short test suite")

    # Clean up: extract just the markdown if wrapped in code blocks
    if "```markdown" in result_text:
        start = result_text.index("```markdown") + len("```markdown")
        end = result_text.rindex("```") if result_text.count("```") >= 2 else len(result_text)
        result_text = result_text[start:end].strip()
    elif result_text.startswith("```") and result_text.endswith("```"):
        result_text = result_text[3:-3].strip()

    logger.info(f"Generated LLM test suite: {len(result_text)} chars")
    return result_text


if __name__ == "__main__":
    import asyncio

    async def main():
        spec = await generate_llm_test_suite(
            system_prompt="You are a helpful customer support assistant.",
            app_description="Customer support chatbot for an e-commerce platform",
            focus_areas=["safety", "accuracy", "edge_cases"],
            num_cases=5,
        )
        print(spec)

    asyncio.run(main())
