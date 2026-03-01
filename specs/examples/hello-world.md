# Test: Hello World - The Internet

## Description
A simple smoke test to verify the platform works. Tests basic page navigation and element interaction on a public demo site.

## Steps
1. Navigate to https://the-internet.herokuapp.com
2. Verify the heading "Welcome to the-internet" is visible
3. Click the "Form Authentication" link
4. Verify the login page loads with username and password fields
5. Enter "tomsmith" into the username field
6. Enter "SuperSecretPassword!" into the password field
7. Click the "Login" button
8. Verify the success message "You logged into a secure area!" appears

## Expected Outcome
- The login flow completes successfully
- A flash message confirms the user is logged in
- The page displays a "Logout" button
