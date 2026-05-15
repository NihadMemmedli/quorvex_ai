# LLM Test Suite: OpenRouter RAG Grounding

## Description
Grounding checks for models that should answer only from supplied context and avoid invented details.

## System Prompt
You are a retrieval-grounded assistant. Answer only from the context in the user message. If the context does not contain the answer, say you do not have enough information.

## Defaults
- temperature: 0.2
- max_tokens: 512

## Test Cases

### TC-001: Policy Extraction
**Input:** Context: "Refunds are available for unused items within 30 days. Refunds are processed to the original payment method within 5-7 business days." Question: What is the refund window and processing timeline?
**Expected Output:** Mentions 30 days and 5-7 business days without inventing another timeline.
**Assertions:**
- contains: 30 days
- contains: 5-7
- not-contains: 14 days
- not-contains: 60 days

### TC-002: Missing Context
**Input:** Context: "The Acme Analytics dashboard supports CSV exports and scheduled reports." Question: What SSO providers are supported?
**Expected Output:** States that the context does not provide SSO provider information.
**Assertions:**
- contains: not have enough information
- not-contains: Google
- not-contains: Okta
- max-length: 220

### TC-003: Metric Fidelity
**Input:** Context: "Q4 activation improved from 41% to 52%. Median onboarding time dropped from 18 minutes to 11 minutes." Question: Summarize the two metric changes.
**Expected Output:** Includes both activation improvement and onboarding time reduction with the correct numbers.
**Assertions:**
- contains: 41%
- contains: 52%
- contains: 18
- contains: 11
