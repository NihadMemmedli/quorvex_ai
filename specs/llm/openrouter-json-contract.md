# LLM Test Suite: OpenRouter JSON Contract

## Description
Checks whether models can produce compact machine-readable JSON for application workflows.

## System Prompt
You convert user requests into strict JSON. Return JSON only. Do not wrap the JSON in markdown.

## Defaults
- temperature: 0.1
- max_tokens: 256

## Test Cases

### TC-001: Bug Ticket JSON
**Input:** Create a JSON ticket for: Login button shows a spinner forever on Safari after invalid password. Severity high. Area authentication.
**Expected Output:** Valid JSON including title, severity, and area.
**Assertions:**
- json-valid: true
- contains: high
- contains: authentication
- not-contains: ``` 

### TC-002: Test Case JSON
**Input:** Create JSON for a test case named "Password reset email" with steps request reset and verify email arrives.
**Expected Output:** Valid JSON describing the test case and its steps.
**Assertions:**
- json-valid: true
- contains: Password reset email
- contains: steps
- max-length: 500
