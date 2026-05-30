# Test: Contact Form Validation

## Description
The system shall validate all contact form fields before enabling the submit button, ensuring complete and properly formatted data is provided.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Contact Form Validation

## Expected Outcome
- Send button remains disabled when any required field is empty
- Send button remains disabled when the terms checkbox is unchecked
- Phone number field enforces +994 format
- Message content field enforces a 1500 character maximum limit
- All required fields must contain valid data for the button to become enabled

## Test Data
- Target URL: https://my.gov.az/serviceCategories
