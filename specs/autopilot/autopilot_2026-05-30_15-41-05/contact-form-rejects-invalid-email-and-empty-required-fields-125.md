# Test: Contact form rejects invalid email and empty required fields

## Description
Validates that the contact form enforces validation: invalid email format is rejected, empty required fields prevent submission, and 1500-character limit on appeal content is enforced.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/contact-us
2. Fill all fields except email — enter 'not-an-email' in email field
3. Check terms acceptance
4. Verify validation error on email field
5. Correct email to valid format
6. Clear the FIN field
7. Verify Göndər button is disabled
8. Re-fill FIN, then enter 1501 characters in appeal content textarea
9. Verify character limit validation message appears

## Expected Outcome
- Invalid email format shows validation error
- Empty FIN field prevents form submission
- Appeal content exceeding 1500 characters triggers validation
- Göndər button remains disabled until all validations pass

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-113
- Source flow(s): Submit Contact Form
