# Test: Checkout shipping state survives refresh

## Objective
Detect stale checkout-state bugs before customers lose progress during payment.

## Steps
1. Start checkout with a logged-in customer.
2. Enter a valid shipping address.
3. Continue to delivery.
4. Refresh the page.
5. Navigate back to shipping.

## Expected Result
The address remains populated and the checkout stepper reflects the current step.
