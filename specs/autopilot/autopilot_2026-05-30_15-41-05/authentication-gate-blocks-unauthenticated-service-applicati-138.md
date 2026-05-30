# Test: Authentication Gate for Service Applications

## Description
The system shall require mygov ID authentication before allowing users to apply for any e-service, displaying a login modal when an unauthenticated user attempts to apply.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Authentication Gate for Service Applications

## Expected Outcome
- Clicking the 'Apply' button (MÜRACİƏT ET) when not logged in triggers a login modal
- Login modal displays the message requiring mygov ID login (e.g., 'Log in to your account! To use this service, please log in with your mygov ID')
- Modal contains a 'Log in' button (DAXİL OLUN)
- The underlying page URL does not change when the modal appears
- User cannot proceed with the application without authenticating

## Test Data
- Target URL: https://my.gov.az/serviceCategories
