# Test: Discount code guardrails

## Objective
Verify discount behavior is predictable and audit-friendly.

## Steps
1. Apply `SPRING15` and confirm the discount is accepted.
2. Apply `EXPIRED20` and confirm an expired-code message.
3. Try to apply `SPRING15` twice.

## Expected Result
Only one valid discount is applied and rejected codes do not change the cart total.
