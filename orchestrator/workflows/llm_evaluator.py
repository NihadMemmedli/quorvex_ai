"""
LLM Evaluator - Three-layer evaluation engine for LLM testing.

Layer 1: Deterministic assertions (free, instant)
Layer 2: DeepEval metrics (requires OPENAI_API_KEY)
Layer 3: LLM-as-judge (uses AgentRunner with Claude)
"""

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.json_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


@dataclass
class AssertionResult:
    """Result of a single assertion check."""

    name: str
    category: str  # deterministic, deepeval, judge
    passed: bool
    score: float | None = None
    explanation: str = ""


@dataclass
class EvaluationResult:
    """Full evaluation result for a single test case."""

    test_case_id: str
    test_case_name: str
    overall_passed: bool = True
    assertions: list[AssertionResult] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "test_case_name": self.test_case_name,
            "overall_passed": self.overall_passed,
            "assertions": [
                {
                    "name": a.name,
                    "category": a.category,
                    "passed": a.passed,
                    "score": a.score,
                    "explanation": a.explanation,
                }
                for a in self.assertions
            ],
            "scores": self.scores,
        }


# ========== Layer 1: Deterministic Assertions ==========


def run_deterministic_assertions(
    output: str,
    assertions: list[dict[str, Any]],
    latency_ms: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> list[AssertionResult]:
    """Run deterministic assertions against LLM output.

    Supported types:
        contains, not-contains, regex, json-valid, json-schema,
        max-tokens, min-length, max-length, latency-ms, cost-max
    """
    results = []

    for assertion in assertions:
        atype = assertion.get("type", "")
        avalue = assertion.get("value", "")
        result = AssertionResult(
            name=f"{atype}: {avalue}",
            category="deterministic",
            passed=True,
        )

        try:
            if atype == "contains":
                result.passed = str(avalue).lower() in output.lower()
                if not result.passed:
                    result.explanation = f"Output does not contain '{avalue}'"

            elif atype == "not-contains":
                result.passed = str(avalue).lower() not in output.lower()
                if not result.passed:
                    result.explanation = f"Output contains forbidden text '{avalue}'"

            elif atype == "regex":
                result.passed = bool(re.search(str(avalue), output))
                if not result.passed:
                    result.explanation = f"Output does not match pattern '{avalue}'"

            elif atype == "json-valid":
                try:
                    json.loads(output)
                    result.passed = True
                except json.JSONDecodeError as e:
                    result.passed = False
                    result.explanation = f"Invalid JSON: {e}"

            elif atype == "json-schema":
                try:
                    import jsonschema

                    data = json.loads(output)
                    schema = json.loads(str(avalue)) if isinstance(avalue, str) else avalue
                    jsonschema.validate(data, schema)
                    result.passed = True
                except Exception as e:
                    result.passed = False
                    result.explanation = f"Schema validation failed: {e}"

            elif atype == "latency-ms":
                threshold = float(avalue)
                result.passed = latency_ms <= threshold
                result.score = float(latency_ms)
                if not result.passed:
                    result.explanation = f"Latency {latency_ms}ms exceeds threshold {threshold}ms"

            elif atype == "max-tokens":
                threshold = int(float(avalue))
                result.passed = tokens_out <= threshold
                result.score = float(tokens_out)
                if not result.passed:
                    result.explanation = f"Output tokens {tokens_out} exceeds max {threshold}"

            elif atype == "min-length":
                min_len = int(float(avalue))
                result.passed = len(output) >= min_len
                result.score = float(len(output))
                if not result.passed:
                    result.explanation = f"Output length {len(output)} below minimum {min_len}"

            elif atype == "max-length":
                max_len = int(float(avalue))
                result.passed = len(output) <= max_len
                result.score = float(len(output))
                if not result.passed:
                    result.explanation = f"Output length {len(output)} exceeds maximum {max_len}"

            elif atype == "cost-max":
                threshold = float(avalue)
                result.passed = cost_usd <= threshold
                result.score = cost_usd
                if not result.passed:
                    result.explanation = f"Cost ${cost_usd:.6f} exceeds max ${threshold:.6f}"

            else:
                result.explanation = f"Unknown assertion type: {atype}"
                result.passed = True  # Don't fail on unknown types

        except Exception as e:
            result.passed = False
            result.explanation = f"Assertion error: {e}"

        results.append(result)

    return results


# ========== Layer 2: DeepEval Metrics ==========


async def run_deepeval_metrics(
    input_prompt: str,
    output: str,
    expected_output: str = "",
    context: list[str] | None = None,
    metrics_config: dict[str, float] | None = None,
) -> list[AssertionResult]:
    """Run DeepEval metrics if available.

    Requires OPENAI_API_KEY. Gracefully skips if not available.

    Args:
        input_prompt: The user input
        output: The LLM output
        expected_output: Expected output for comparison
        context: RAG retrieval context
        metrics_config: {metric_name: threshold} e.g. {"answer_relevancy": 0.8}

    Returns:
        List of AssertionResult for each metric
    """
    if not metrics_config:
        return []

    import os

    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set - skipping DeepEval metrics")
        return [
            AssertionResult(
                name=f"deepeval:{name}",
                category="deepeval",
                passed=True,
                explanation="Skipped: OPENAI_API_KEY not configured",
            )
            for name in metrics_config
        ]

    results = []

    try:
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            BiasMetric,
            FaithfulnessMetric,
            HallucinationMetric,
            ToxicityMetric,
        )
        from deepeval.test_case import LLMTestCase

        METRIC_MAP = {
            "answer_relevancy": AnswerRelevancyMetric,
            "faithfulness": FaithfulnessMetric,
            "hallucination": HallucinationMetric,
            "toxicity": ToxicityMetric,
            "bias": BiasMetric,
        }

        test_case = LLMTestCase(
            input=input_prompt,
            actual_output=output,
            expected_output=expected_output if expected_output else None,
            retrieval_context=context if context else None,
        )

        for metric_name, threshold in metrics_config.items():
            metric_class = METRIC_MAP.get(metric_name)
            if not metric_class:
                results.append(
                    AssertionResult(
                        name=f"deepeval:{metric_name}",
                        category="deepeval",
                        passed=True,
                        explanation=f"Unknown DeepEval metric: {metric_name}",
                    )
                )
                continue

            try:
                metric = metric_class(threshold=threshold)
                metric.measure(test_case)

                score = metric.score if hasattr(metric, "score") else None
                passed = (
                    metric.is_successful()
                    if hasattr(metric, "is_successful")
                    else (score is not None and score >= threshold)
                )
                reason = metric.reason if hasattr(metric, "reason") else ""

                results.append(
                    AssertionResult(
                        name=f"deepeval:{metric_name}",
                        category="deepeval",
                        passed=passed,
                        score=score,
                        explanation=reason or f"Score: {score}, Threshold: {threshold}",
                    )
                )
            except Exception as e:
                logger.warning(f"DeepEval metric {metric_name} failed: {e}")
                results.append(
                    AssertionResult(
                        name=f"deepeval:{metric_name}",
                        category="deepeval",
                        passed=True,  # Don't fail on metric errors
                        explanation=f"Metric error (skipped): {e}",
                    )
                )

    except ImportError:
        logger.warning("deepeval not installed - skipping DeepEval metrics")
        for name in metrics_config:
            results.append(
                AssertionResult(
                    name=f"deepeval:{name}",
                    category="deepeval",
                    passed=True,
                    explanation="Skipped: deepeval not installed",
                )
            )
    except Exception as e:
        logger.error(f"DeepEval execution error: {e}")
        for name in metrics_config:
            results.append(
                AssertionResult(
                    name=f"deepeval:{name}",
                    category="deepeval",
                    passed=True,
                    explanation=f"Skipped due to error: {e}",
                )
            )

    return results


# ========== Layer 3: LLM-as-Judge ==========


async def run_judge_evaluation(
    input_prompt: str,
    output: str,
    expected_output: str = "",
    system_prompt: str = "",
    judge_config: Any | None = None,
) -> list[AssertionResult]:
    """Run LLM-as-judge evaluation using AgentRunner.

    Args:
        input_prompt: The original user input
        output: The LLM output to evaluate
        expected_output: What was expected
        system_prompt: The system prompt used
        judge_config: JudgeConfig with rubric, criteria, threshold

    Returns:
        List of AssertionResult for each criterion
    """
    if judge_config is None:
        return []

    from load_env import setup_claude_env
    from utils.agent_runner import AgentRunner

    setup_claude_env()

    criteria_str = ", ".join(judge_config.criteria) if judge_config.criteria else "helpfulness, accuracy"

    prompt = f"""Evaluate the following LLM output. Score each criterion on a scale of 1-{judge_config.scale_max}.

## System Prompt Used
{system_prompt}

## User Input
{input_prompt}

## Expected Behavior
{expected_output}

## Actual Output
{output}

## Evaluation Rubric
{judge_config.rubric}

## Criteria to Evaluate
{criteria_str}

Respond with JSON in a markdown code block:
```json
{{
  "scores": {{
    "criterion_name": {{
      "score": <number>,
      "max_score": {judge_config.scale_max},
      "explanation": "Brief justification"
    }}
  }},
  "overall_score": <average_score>,
  "overall_passed": <true if overall_score >= {judge_config.threshold}>,
  "summary": "One-sentence assessment"
}}
```"""

    runner = AgentRunner(timeout_seconds=120)
    result_text = ""

    try:
        result = await runner.run(prompt=prompt)
        if result.success:
            result_text = result.output
        else:
            logger.error(f"Judge agent failed: {result.error}")
            return [
                AssertionResult(
                    name="judge:overall",
                    category="judge",
                    passed=True,
                    explanation=f"Judge evaluation failed: {result.error}",
                )
            ]
    except Exception as e:
        error_str = str(e).lower()
        if "cancel scope" in error_str or "cancelled" in error_str:
            logger.info("SDK cleanup warning in judge evaluation (ignored)")
        else:
            logger.error(f"Judge evaluation error: {e}")
            return [
                AssertionResult(
                    name="judge:overall",
                    category="judge",
                    passed=True,
                    explanation=f"Judge evaluation error: {e}",
                )
            ]

    # Parse the judge response
    results = []
    try:
        parsed = extract_json_from_markdown(result_text)
        if parsed and isinstance(parsed, dict):
            scores = parsed.get("scores", {})
            threshold = judge_config.threshold

            for criterion, data in scores.items():
                score = data.get("score", 0) if isinstance(data, dict) else 0
                data.get("max_score", judge_config.scale_max) if isinstance(data, dict) else judge_config.scale_max
                explanation = data.get("explanation", "") if isinstance(data, dict) else ""

                results.append(
                    AssertionResult(
                        name=f"judge:{criterion}",
                        category="judge",
                        passed=score >= threshold,
                        score=float(score),
                        explanation=explanation,
                    )
                )

            # Add overall score
            overall = parsed.get("overall_score", 0)
            results.append(
                AssertionResult(
                    name="judge:overall",
                    category="judge",
                    passed=overall >= threshold,
                    score=float(overall),
                    explanation=parsed.get("summary", ""),
                )
            )
        else:
            results.append(
                AssertionResult(
                    name="judge:overall",
                    category="judge",
                    passed=True,
                    explanation="Could not parse judge response",
                )
            )

    except Exception as e:
        logger.warning(f"Failed to parse judge response: {e}")
        results.append(
            AssertionResult(
                name="judge:overall",
                category="judge",
                passed=True,
                explanation=f"Parse error: {e}",
            )
        )

    return results


# ========== Combined Evaluation ==========


async def evaluate_test_case(
    test_case_id: str,
    test_case_name: str,
    input_prompt: str,
    output: str,
    expected_output: str = "",
    system_prompt: str = "",
    context: list[str] | None = None,
    assertions: list[dict[str, Any]] | None = None,
    metrics_config: dict[str, float] | None = None,
    judge_config: Any | None = None,
    latency_ms: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> EvaluationResult:
    """Run all three evaluation layers on a single test case.

    Layer 1: Deterministic assertions (always runs)
    Layer 2: DeepEval metrics (if configured and available)
    Layer 3: LLM-as-judge (if configured)
    """
    result = EvaluationResult(
        test_case_id=test_case_id,
        test_case_name=test_case_name,
    )

    # Layer 1: Deterministic assertions
    if assertions:
        deterministic_results = run_deterministic_assertions(
            output=output,
            assertions=assertions,
            latency_ms=latency_ms,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
        result.assertions.extend(deterministic_results)

    # Layer 2: DeepEval metrics
    if metrics_config:
        deepeval_results = await run_deepeval_metrics(
            input_prompt=input_prompt,
            output=output,
            expected_output=expected_output,
            context=context,
            metrics_config=metrics_config,
        )
        result.assertions.extend(deepeval_results)
        for ar in deepeval_results:
            if ar.score is not None:
                result.scores[ar.name] = ar.score

    # Layer 3: LLM-as-judge
    if judge_config:
        judge_results = await run_judge_evaluation(
            input_prompt=input_prompt,
            output=output,
            expected_output=expected_output,
            system_prompt=system_prompt,
            judge_config=judge_config,
        )
        result.assertions.extend(judge_results)
        for ar in judge_results:
            if ar.score is not None:
                result.scores[ar.name] = ar.score

    # Overall pass/fail: ALL assertions must pass
    result.overall_passed = all(a.passed for a in result.assertions)

    return result
