"""
Dataset Augmentor - AI-powered test case generation for LLM datasets.

Uses Claude to generate additional test cases based on existing dataset cases,
with configurable focus areas: edge_cases, adversarial, boundary, rephrase.
"""

import json
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger
from utils.agent_runner import AgentRunner
from utils.json_utils import extract_json_from_markdown

logger = get_logger(__name__)


async def augment_dataset(
    cases: list[dict],
    focus: str = "edge_cases",
    num_cases: int = 5,
    dataset_name: str = "",
    dataset_description: str = "",
) -> list[dict]:
    """Generate additional test cases for a dataset using AI.

    Args:
        cases: Existing cases as dicts with input_prompt, expected_output, context, assertions
        focus: Generation focus - edge_cases, adversarial, boundary, rephrase
        num_cases: Number of new cases to generate
        dataset_name: Name of the dataset for context
        dataset_description: Description of the dataset for context

    Returns:
        List of generated case dicts matching DatasetCase structure

    Raises:
        RuntimeError: If generation fails or produces no results
    """
    setup_claude_env()

    # Build focus description
    focus_descriptions = {
        "edge_cases": "Generate edge case scenarios that test boundary conditions, unusual inputs, and corner cases that might break the system.",
        "adversarial": "Generate adversarial inputs designed to test the system's robustness - prompt injections, misleading context, ambiguous queries, and inputs that try to confuse or manipulate the model.",
        "boundary": "Generate boundary value test cases - minimum/maximum lengths, empty inputs, special characters, Unicode, extremely long prompts, and format edge cases.",
        "rephrase": "Generate rephrased versions of existing test cases - same intent but different wording, tone, formality, and structure to test consistency.",
    }
    focus_desc = focus_descriptions.get(focus, focus_descriptions["edge_cases"])

    # Format existing cases as examples (up to 10)
    examples_text = ""
    for i, c in enumerate(cases[:10]):
        examples_text += f"\n--- Example {i + 1} ---\n"
        examples_text += f"Input: {c.get('input_prompt', '')}\n"
        if c.get("expected_output"):
            examples_text += f"Expected Output: {c['expected_output']}\n"
        if c.get("context"):
            examples_text += f"Context: {json.dumps(c['context'])}\n"
        if c.get("assertions"):
            examples_text += f"Assertions: {json.dumps(c['assertions'])}\n"

    prompt = f"""You are a test case generator for LLM evaluation datasets.

Dataset: {dataset_name or "Unnamed"}
Description: {dataset_description or "No description"}

EXISTING TEST CASES ({len(cases)} total, showing up to 10):
{examples_text}

TASK: {focus_desc}

Generate exactly {num_cases} NEW test cases that are diverse and different from the existing ones.

Return a JSON array where each element has:
- "input_prompt": string (the test input)
- "expected_output": string (expected response or empty string if open-ended)
- "context": array of strings (any context documents, can be empty array)
- "assertions": array of objects with "type" and "value" keys (e.g. {{"type": "contains", "value": "keyword"}})
- "tags": array of strings (relevant tags including "{focus}")

Return ONLY the JSON array, no other text.

```json
[
  {{
    "input_prompt": "...",
    "expected_output": "...",
    "context": [],
    "assertions": [],
    "tags": ["{focus}"]
  }}
]
```"""

    # Cancel scope pattern: declare result_text OUTSIDE the try block
    result_text = ""

    try:
        runner = AgentRunner(timeout_seconds=300)
        result = await runner.run(prompt=prompt)
        if result.success:
            result_text = result.output
        else:
            raise RuntimeError(f"AI augmentation failed: {result.error}")
    except Exception as e:
        error_str = str(e).lower()
        if "cancel" in error_str or "scope" in error_str:
            logger.warning(f"Cancel scope during augmentation (may have partial result): {e}")
        else:
            if not result_text:
                raise RuntimeError(f"Dataset augmentation failed: {e}")

    # Validation runs AFTER except block regardless of cancel scope
    if not result_text:
        raise RuntimeError("Dataset augmentation produced no output")

    generated = extract_json_from_markdown(result_text)

    if not isinstance(generated, list):
        raise RuntimeError("Expected JSON array from augmentation")

    if len(generated) == 0:
        raise RuntimeError("Augmentation produced empty results")

    # Normalize each case to match DatasetCase structure
    normalized = []
    for case in generated:
        if not isinstance(case, dict):
            continue
        normalized.append(
            {
                "input_prompt": case.get("input_prompt", ""),
                "expected_output": case.get("expected_output", ""),
                "context": case.get("context", []),
                "assertions": case.get("assertions", []),
                "tags": case.get("tags", [focus]),
            }
        )

    if not normalized:
        raise RuntimeError("No valid cases produced by augmentation")

    logger.info(f"Generated {len(normalized)} augmented cases (focus={focus})")
    return normalized


if __name__ == "__main__":
    import asyncio

    from logging_config import setup_logging

    setup_logging()

    sample_cases = [
        {
            "input_prompt": "What is 2+2?",
            "expected_output": "4",
            "context": [],
            "assertions": [{"type": "contains", "value": "4"}],
        },
        {
            "input_prompt": "Translate 'hello' to French",
            "expected_output": "bonjour",
            "context": [],
            "assertions": [{"type": "contains", "value": "bonjour"}],
        },
    ]
    result = asyncio.run(
        augment_dataset(
            sample_cases,
            focus="edge_cases",
            num_cases=3,
            dataset_name="Test Dataset",
        )
    )
    print(json.dumps(result, indent=2))
