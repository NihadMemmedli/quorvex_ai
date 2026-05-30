# Test: Document verification form requires consent and provides feedback on submission

## Description
Validates the document verification form behavior: consent checkbox must be checked, document number must be entered, and the system provides visible feedback after submission. This test targets the observed issue where no feedback was shown for invalid input.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Verify the consent checkbox with legal disclaimer is displayed
3. Verify a text input field for document number is present
4. Verify the 'Yoxla' (Check) button is present
5. Leave the consent checkbox unchecked and the document number empty
6. Click the 'Yoxla' button
7. Verify the form is not submitted (button disabled or no action)
8. Check the consent checkbox and enter an invalid document number 'INVALID-TEST'
9. Click the 'Yoxla' button
10. Observe the page for any visible response (error message, validation feedback, or loading indicator)
11. Wait up to 10 seconds for any asynchronous response
12. Verify whether form values are retained after submission

## Expected Outcome
- Form cannot be submitted without consent checkbox checked and document number entered
- After submission with invalid number, a visible response SHOULD be displayed (error/validation message) — if not, this is a bug
- Form values are retained if the page does not navigate
- Any response message is clearly visible without requiring scroll

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-127, REQ-128
- Source flow(s): Document Verification with Invalid Number
