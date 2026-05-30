# Test: Contact form submission requires all fields and terms acceptance

## Description
Validates the contact form happy path: identity card series, number, FIN, phone, email, appeal type, content, and terms checkbox must all be completed before the Göndər button is enabled.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/contact-us
2. Verify Göndər (Send) button is disabled initially
3. Select identity card series (e.g., 'AA')
4. Enter identity card number
5. Enter FIN code
6. Enter contact number in +994 format
7. Enter valid email address
8. Select appeal type from dropdown
9. Enter appeal content (within 1500 characters)
10. Check terms acceptance checkbox
11. Verify Göndər button becomes enabled
12. Click Göndər button

## Expected Outcome
- Button is disabled until all fields are filled and terms accepted
- All form fields accept valid input
- Form submits successfully after all validations pass

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-101, REQ-113
- Source flow(s): Submit Contact Form
