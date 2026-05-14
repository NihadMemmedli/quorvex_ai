# Test: Browse Social Protection category and verify 16 services render

## Description
Validates the primary navigation happy path from home to a populated category detail page, ensuring the service catalog is fetched and rendered for Social Protection.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en
2. Open the Categories taxonomy from the home page
3. Verify the Categories listing page is reachable at /en/serviceCategories and shows 15 categories
4. Click the 'Social Protection' category link
5. Wait for navigation to /en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f
6. Wait for full hydration (allow up to 5+ seconds)
7. Count the service entries rendered on the category page
8. Inspect each service card for name, icon, and external resource links

## Expected Outcome
- URL is /en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f after click
- Exactly 16 Social Protection services are displayed
- Each service shows a name and icon
- Each service exposes 2-3 external resource links
- GET requests to /dg-catalog/api/v1/services/by-label?label=SOCIAL_PROTECTION and /dg-catalog/api/v1/seo/by-label?label=SOCIAL_PROTECTION return 2xx

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-063, REQ-064, REQ-076
- Source flow(s): Browse Social Protection service category, Browse Categories taxonomy
- Observed API endpoint(s): https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/services/by-label?label=SOCIAL_PROTECTION, https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/seo/by-label?label=SOCIAL_PROTECTION
