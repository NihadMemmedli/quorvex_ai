# Test: Order confirmation includes payment and fulfillment signals

## Objective
Confirm successful checkout leaves enough evidence for support and QA triage.

## Steps
1. Complete checkout with a valid test card.
2. Land on `/orders/:id/confirmation`.
3. Verify order number, paid status, email receipt message, and estimated delivery.

## Expected Result
The order confirmation page displays a stable order number and captured payment status.
