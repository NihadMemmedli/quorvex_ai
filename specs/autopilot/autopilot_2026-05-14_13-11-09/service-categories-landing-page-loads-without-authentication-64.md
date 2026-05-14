# Test: Service categories landing page loads without authentication

## Description
Validates that the entry-point service categories page is publicly accessible and renders successfully, ensuring users can discover available government services.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f
2. Wait for the page to load completely
3. Verify the page returns a 200 status
4. Verify service category content is visible

## Expected Outcome
- Page loads successfully without requiring login
- Service category listings are visible to the user
- No navigation errors are displayed

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-055, REQ-061
