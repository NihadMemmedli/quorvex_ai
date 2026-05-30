# Test: Login Prompt Modal on Service Application

## Description
The system shall display an inline login prompt modal (not a page redirect) when an unauthenticated user attempts to apply for a service, keeping the user on the same page URL while presenting authentication options.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Login Prompt Modal on Service Application

## Expected Outcome
- Clicking MÜRACIƏT ET on a service detail page shows a modal overlay
- Modal displays heading text 'Hesaba daxil olun!' (Log in to your account)
- Modal displays informational message about logging in via mygov ID
- Modal includes a DAXİL OLUN (Login) button
- Page URL does not change when the modal appears
- Modal can be dismissed (implicit: clicking outside or close button)
- Clicking DAXİL OLUN in the modal navigates to https://mygovid.gov.az/auth

## Test Data
- Target URL: https://my.gov.az/serviceCategories
