# Test: Login session recovers before checkout

## Objective
Prevent customers from losing checkout intent after a session timeout.

## Steps
1. Open `/checkout` with an expired auth cookie.
2. Verify the app redirects to `/login?returnTo=/checkout`.
3. Sign in as `qa.checkout@example.com`.
4. Verify checkout resumes at the shipping step.

## Expected Result
Login succeeds and the customer returns to checkout with the cart intact.
