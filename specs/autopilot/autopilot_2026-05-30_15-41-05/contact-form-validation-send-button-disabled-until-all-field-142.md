# Test: Contact form validation: send button disabled until all fields complete and terms accepted

## Description
Validates progressive form validation behavior where the Send button remains disabled until every required field is filled and the terms checkbox is checked.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/contact-us
2. Verify the form fields: ID card serial, ID card number, FIN, phone (+994 format), email, application type, message textarea
3. Verify the 'Göndər' (Send) button is disabled by default
4. Fill only the ID card number and FIN fields
5. Verify the Send button is still disabled
6. Fill all remaining fields: phone (+994 50 123 45 67), email (test@example.com), select application type 'İlkin müraciət', enter message text
7. Verify the Send button is still disabled (terms not accepted)
8. Check the terms acceptance checkbox
9. Verify the Send button becomes enabled
10. Uncheck the terms checkbox
11. Verify the Send button becomes disabled again

## Expected Outcome
- Send button is disabled when the page loads
- Send button remains disabled when any required field is empty
- Send button remains disabled when terms checkbox is unchecked even if all fields are filled
- Send button becomes enabled only when all fields are filled AND terms are accepted
- Toggling the terms checkbox toggles the button enabled/disabled state

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-131, REQ-132
- Source flow(s): Fill Contact Form (Not Submitted)
