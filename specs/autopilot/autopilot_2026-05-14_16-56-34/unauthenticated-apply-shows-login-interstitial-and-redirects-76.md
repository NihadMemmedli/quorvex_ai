# Test: Unauthenticated APPLY shows login interstitial and redirects to mygovid.gov.az

## Description
Validates the critical authentication gate: clicking APPLY on a service while unauthenticated must show a Login interstitial and the LOGIN CTA must cross-domain redirect to the identity provider.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/services/retirement-calculator as an unauthenticated user
2. Verify the service detail page displays an APPLY button
3. Click the APPLY button
4. Verify the Login required interstitial modal appears and URL remains on the service detail page
5. Click the LOGIN CTA in the interstitial
6. Wait for cross-domain navigation

## Expected Outcome
- Login required interstitial is shown after clicking APPLY
- URL remains https://my.gov.az/en/services/retirement-calculator until LOGIN is clicked
- Clicking LOGIN redirects to https://mygovid.gov.az/auth
- Destination auth page loads successfully without error

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-069, REQ-070, REQ-077
- Source flow(s): Apply for service requires authentication
