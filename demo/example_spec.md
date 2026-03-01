# Test: Login Form Validation

## Description
Test the login form on a demo application. Verify that form validation works correctly and that successful login redirects to the dashboard.

## Steps

1. Navigate to https://the-internet.herokuapp.com/login
2. Verify the heading "Login Page" is visible
3. Enter "tomsmith" into the Username field
4. Enter "SuperSecretPassword!" into the Password field
5. Click the "Login" button
6. Verify the page displays "Secure Area" heading
7. Verify a success flash message is visible
8. Click the "Logout" button
9. Verify the user is redirected back to the login page

## Expected Outcome
- Login form accepts valid credentials
- Successful login shows the secure area page
- Logout returns the user to the login page
