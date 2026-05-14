# Test: Contact Us Send button remains disabled until all required fields are valid

## Description
Validates the form submission gate: the Send button must only enable when every required field is populated, formats are valid, and the terms checkbox is checked.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/en/contact
2. Verify the Send button is initially disabled
3. Fill the ID series (AA...) field
4. Fill the ID number field
5. Fill the PIN code field
6. Fill the phone field using +994 format
7. Fill the email field with a valid email
8. Select an Application type (Initial or Repeat)
9. Enter a description (within 1500 characters)
10. Verify Send remains disabled until the terms checkbox is checked
11. Check the terms checkbox
12. Verify Send is now enabled

## Expected Outcome
- Send button is disabled on initial render
- Send button remains disabled while any required field is empty or invalid
- Send button remains disabled while the terms checkbox is unchecked
- Send button becomes enabled only after all required fields are valid AND terms checkbox is checked

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-072
- Source flow(s): Contact Us form submission with validation
