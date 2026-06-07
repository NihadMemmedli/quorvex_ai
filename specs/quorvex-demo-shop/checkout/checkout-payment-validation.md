# Test: Checkout rejects invalid payment data

## Base URL
https://demo-shop.quorvex.local

## Objective
Make failed payment validation actionable by checking the visible error, cart preservation, and retry path.

## Preconditions
- Customer is signed in as `qa.checkout@example.com`.
- Cart contains Everyday Backpack and USB-C Cable.
- Checkout is on the payment step.

## Steps
1. Open `/checkout`.
2. Fill card number `4242 4242 4242 4242`.
3. Fill expiry `01/20`.
4. Click **Pay now**.
5. Verify inline expiry validation appears.
6. Verify the order is not created.
7. Verify cart total remains `$86.40`.

## Expected Result
The checkout blocks submission, explains the validation issue, preserves cart state, and keeps the customer on the payment step.
