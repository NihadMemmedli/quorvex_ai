"""
Load Test Generator Workflow - Converts Load Test Specs to K6 Scripts

This workflow generates K6 JavaScript load test scripts from markdown specs.
It uses an AI agent to parse the spec and produce a properly structured K6 script
with stages, thresholds, checks, and handleSummary() for JSON output.

Unlike browser test generators, this does NOT need browser MCP tools - it generates
K6 JavaScript code directly from the spec using AI.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Store project base directory BEFORE any chdir() calls
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

import logging

from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout

logger = logging.getLogger(__name__)


class LoadTestGenerator:
    """
    K6 Load Test Script Generator that converts markdown specs to executable K6 scripts.

    This does NOT use browser MCP tools. It generates K6 JavaScript code directly
    from the spec since load tests are HTTP-based and don't need browser exploration.

    Flow:
    1. Read the markdown spec file
    2. Extract target URL, endpoints, load profile, thresholds
    3. Build prompt with K6 generation instructions
    4. Run agent via AgentRunner (no MCP tools needed)
    5. Extract JavaScript code from response
    6. Write to scripts/load/<name>.k6.js
    """

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id
        self.scripts_dir = BASE_DIR / "scripts" / "load"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        spec_path: str,
        output_name: str | None = None,
    ) -> Path:
        """
        Generate a K6 load test script from a markdown spec.

        Args:
            spec_path: Path to the markdown spec file
            output_name: Override for output script file name (without extension)

        Returns:
            Path to the generated K6 script file
        """
        spec_path_obj = Path(spec_path)
        if not spec_path_obj.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_path_obj.read_text()
        spec_name = output_name if output_name else spec_path_obj.stem

        # Determine output path
        output_path = self.scripts_dir / f"{spec_name}.k6.js"

        logger.info(f"[load-gen] Generating K6 script from: {spec_path}")
        logger.info(f"   Output: {output_path}")

        # Extract metadata from the spec
        target_url = self._extract_target_url(spec_content)
        test_type = self._extract_test_type(spec_content)
        endpoints = self._extract_endpoints(spec_content)
        load_profile = self._extract_load_profile(spec_content)
        thresholds = self._extract_thresholds(spec_content)
        credentials = self._extract_credential_placeholders(spec_content)

        # Build prompt for the K6 generator agent
        prompt = self._build_generator_prompt(
            spec_path=str(spec_path_obj.resolve()),
            spec_content=spec_content,
            spec_name=spec_name,
            output_path=str(output_path),
            target_url=target_url,
            test_type=test_type,
            endpoints=endpoints,
            load_profile=load_profile,
            thresholds=thresholds,
            credentials=credentials,
        )

        # Invoke the Load Test Generator Agent
        logger.info("[load-gen] Invoking K6 Generator Agent...")
        result = await self._query_agent(prompt)

        # Check if agent wrote the file directly
        if output_path.exists():
            content = output_path.read_text()
            if "export default function" in content or "export function" in content:
                logger.info(f"[load-gen] K6 script generated: {output_path}")
                return output_path

        # Fallback: Extract code from agent response and write it
        if result:
            code = self._extract_code(result)
            if code:
                logger.info(f"[load-gen] Saving generated K6 script to: {output_path}")
                output_path.write_text(code)
                return output_path

        raise RuntimeError("Generator finished but no valid K6 script was produced. Check agent output for errors.")

    def _extract_target_url(self, spec_content: str) -> str | None:
        """Extract target URL from spec content."""
        patterns = [
            r"##\s+Target\s+URL:\s*(https?://[^\s]+)",
            r"Target\s+URL:\s*(https?://[^\s]+)",
            r"##\s+Base\s+URL:\s*(https?://[^\s]+)",
            r"Base\s+URL:\s*(https?://[^\s]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, spec_content, re.IGNORECASE)
            if match:
                return match.group(1).rstrip(".")
        return None

    def _extract_test_type(self, spec_content: str) -> str:
        """Extract test type (load, stress, spike, soak) from spec content."""
        patterns = [
            r"##\s+Type:\s*(\w+)",
            r"Type:\s*(\w+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, spec_content, re.IGNORECASE)
            if match:
                return match.group(1).strip().lower()
        return "load"

    def _extract_endpoints(self, spec_content: str) -> list:
        """Extract endpoint definitions from spec content."""
        endpoints = []
        # Match numbered endpoint lines like "1. POST /auth/login with body {...}"
        pattern = r"\d+\.\s+(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s]*)(.*?)(?=\n\d+\.|\n##|\Z)"
        matches = re.finditer(pattern, spec_content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            method = match.group(1).upper()
            path = match.group(2).strip()
            details = match.group(3).strip()
            endpoints.append(
                {
                    "method": method,
                    "path": path,
                    "details": details,
                }
            )
        return endpoints

    def _extract_load_profile(self, spec_content: str) -> str | None:
        """Extract load profile section from spec content."""
        pattern = r"##\s+Load\s+Profile\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, spec_content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _extract_thresholds(self, spec_content: str) -> str | None:
        """Extract thresholds section from spec content."""
        pattern = r"##\s+Thresholds?\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, spec_content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _extract_credential_placeholders(self, spec_content: str) -> dict:
        """Extract {{VAR}} placeholders from spec."""
        placeholders = {}
        matches = re.findall(r"\{\{([^}]+)\}\}", spec_content)
        for var_name in set(matches):
            env_val = os.environ.get(var_name)
            if env_val:
                placeholders[var_name] = "(set)"
            else:
                placeholders[var_name] = "(NOT SET)"
                logger.warning(f"   Environment variable {var_name} not found in .env")
        return placeholders

    def _build_generator_prompt(
        self,
        spec_path: str,
        spec_content: str,
        spec_name: str,
        output_path: str,
        target_url: str | None,
        test_type: str,
        endpoints: list,
        load_profile: str | None,
        thresholds: str | None,
        credentials: dict,
    ) -> str:
        """Build prompt for the K6 load test generator agent."""

        test_title = spec_name.replace("-", " ").replace("_", " ").title()

        target_url_section = ""
        if target_url:
            target_url_section = f"\nTarget URL: {target_url}"

        endpoints_section = ""
        if endpoints:
            ep_lines = []
            for ep in endpoints:
                ep_lines.append(f"- {ep['method']} {ep['path']} {ep['details']}")
            endpoints_section = "\nExtracted Endpoints:\n" + "\n".join(ep_lines)

        load_profile_section = ""
        if load_profile:
            load_profile_section = f"\nExtracted Load Profile:\n{load_profile}"

        thresholds_section = ""
        if thresholds:
            thresholds_section = f"\nExtracted Thresholds:\n{thresholds}"

        credentials_section = ""
        if credentials:
            cred_lines = []
            for var_name, status in credentials.items():
                cred_lines.append(f"- `{{{{{var_name}}}}}` -> Use `__ENV.{var_name}` in K6 script {status}")
            credentials_section = f"""

## Credentials (IMPORTANT)
The spec contains credential placeholders. In the generated K6 script, use `__ENV.VAR_NAME` for each.

{chr(10).join(cred_lines)}

When running the test, users pass these via: `k6 run -e VAR_NAME=value script.js`
"""

        prompt = f"""You are the K6 Load Test Script Generator.

Context: Generate a K6 load test script from the following spec.

<test-title>{test_title}</test-title>
<test-type>{test_type}</test-type>
<output-file>{output_path}</output-file>
{target_url_section}
{endpoints_section}
{load_profile_section}
{thresholds_section}
{credentials_section}

<spec-content file="{spec_path}">
{spec_content}
</spec-content>

## Instructions

Read the spec file above and generate a complete K6 JavaScript load test script.

### Required Structure

The generated K6 script MUST include:

1. **Imports**: Import from 'k6/http', 'k6', and 'k6/metrics'
   ```javascript
   import http from 'k6/http';
   import {{ check, sleep, group }} from 'k6';
   import {{ Rate, Trend, Counter }} from 'k6/metrics';
   ```

2. **Custom metrics**: Define custom metrics for tracking specific behaviors
   ```javascript
   const errorRate = new Rate('errors');
   const loginDuration = new Trend('login_duration');
   ```

3. **Options object**: With stages and thresholds from the spec
   ```javascript
   export const options = {{
     stages: [
       {{ duration: '30s', target: 20 }},
       {{ duration: '1m', target: 20 }},
       {{ duration: '10s', target: 0 }},
     ],
     thresholds: {{
       http_req_duration: ['p(95)<500'],
       http_req_failed: ['rate<0.01'],
     }},
   }};
   ```

4. **Default function**: The main test function with groups, checks, and sleep
   ```javascript
   export default function () {{
     group('Endpoint Name', function () {{
       const res = http.get('https://api.example.com/endpoint');
       check(res, {{
         'status is 200': (r) => r.status === 200,
         'response time < 500ms': (r) => r.timings.duration < 500,
       }});
     }});
     sleep(1);
   }}
   ```

5. **handleSummary function**: For structured JSON output
   ```javascript
   export function handleSummary(data) {{
     return {{
       'summary.json': JSON.stringify(data),
     }};
   }}
   ```

### K6 Best Practices to Follow

- Use `group()` to organize requests by endpoint or user flow
- Use `check()` for response validation (status codes, body content, timing)
- Use `__ENV.VAR_NAME` for ALL credential placeholders (NEVER hardcode secrets)
- Add `sleep()` between iterations to simulate realistic user think time (1-3 seconds)
- Use proper K6 stages for the load profile (ramp-up, steady, ramp-down)
- Map thresholds from the spec to K6 threshold syntax
- For auth flows, chain requests (e.g., login first, use token in subsequent requests)
- Use `http.batch()` for independent parallel requests when appropriate
- Add descriptive names to checks for clear reporting
- Store auth tokens in variables and reuse across requests within the same iteration

### Test Type Mapping

- **load**: Standard load test with ramp-up, steady state, ramp-down
- **stress**: Progressively increase beyond normal load to find breaking point
- **spike**: Sudden large spike in traffic
- **soak**: Extended duration at moderate load to find memory leaks / degradation

### Threshold Syntax Mapping

- `http_req_duration p(95) < 500ms` -> `http_req_duration: ['p(95)<500']`
- `http_req_duration p(99) < 1000ms` -> `http_req_duration: ['p(99)<1000']`
- `http_req_failed rate < 1%` -> `http_req_failed: ['rate<0.01']`
- `http_req_failed rate < 5%` -> `http_req_failed: ['rate<0.05']`
- `http_reqs count > 100` -> `http_reqs: ['count>100']`

## Output

Write the generated K6 script to: {output_path}

The script must be valid JavaScript that can be run with `k6 run {output_path}`.
Return ONLY the JavaScript code inside a ```javascript code block.
"""
        return prompt

    async def _query_agent(self, prompt: str) -> str:
        """Query the K6 Load Test Generator agent using AgentRunner."""
        timeout = int(
            os.environ.get(
                "K6_GENERATOR_TIMEOUT_SECONDS", os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout())
            )
        )

        logger.info(f"   Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=["Glob", "Grep", "Read", "LS", "Write"],
            log_tools=True,
        )

        result = await runner.run(prompt)

        # Log diagnostics
        logger.info(
            f"   Agent stats: {result.messages_received} messages, "
            f"{len(result.tool_calls)} tool calls, "
            f"{result.duration_seconds:.1f}s"
        )

        if result.timed_out:
            logger.warning("   Agent timed out")

        if not result.success and result.error:
            logger.warning(f"   Agent error: {result.error}")

        return result.output

    def _extract_code(self, text: str) -> str | None:
        """Extract JavaScript code from markdown response."""
        patterns = [
            r"```javascript\n(.*?)```",
            r"```js\n(.*?)```",
            r"```\n(.*?)```",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                code = match.group(1).strip()
                # Validate it looks like a K6 script
                if "export default function" in code or "export function" in code:
                    return code

        # Fallback: if the entire response looks like code
        if text.strip().startswith("import") and "export default function" in text:
            return text.strip()

        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate K6 load test scripts from specs")
    parser.add_argument("--spec", required=True, help="Path to the load test spec file")
    parser.add_argument("--output", help="Override output file name (without extension)")
    args = parser.parse_args()

    async def main():
        generator = LoadTestGenerator()
        output = await generator.generate(args.spec, output_name=args.output)
        logger.info(f"Generated K6 script: {output}")

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
