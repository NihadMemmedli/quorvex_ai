# Test: Cart total matches line items, discount, tax, and shipping

## Objective
Catch cart total mismatches that become payment and order reconciliation defects.

## Steps
1. Add Everyday Backpack and USB-C Cable to the cart.
2. Apply discount code `SPRING15`.
3. Select standard shipping.
4. Compare subtotal, discount, tax, shipping, and total.

## Expected Result
The rendered total is `$86.40`, matching the order preview returned by `/api/cart/price-preview`.
