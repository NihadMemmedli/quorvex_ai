# Test: REGRESSION: Service FAQ tab should not navigate to global support page

## Description
Reproduces an observed defect where the 'Frequently asked questions' tab on /en/services/retirement-calculator incorrectly navigates the user to /en/support instead of showing service-specific FAQ content.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/services/retirement-calculator
2. Verify the page exposes a 'Frequently asked questions' tab
3. Click the 'Frequently asked questions' tab
4. Capture the resulting URL and page content

## Expected Outcome
- URL must remain https://my.gov.az/en/services/retirement-calculator after clicking the FAQ tab
- Service-specific FAQ content is rendered on the same page
- User must NOT be navigated to /en/support (currently observed defect — test should FAIL until fixed)

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-075, REQ-077
- Source flow(s): FAQ tab on service detail navigates to global support
