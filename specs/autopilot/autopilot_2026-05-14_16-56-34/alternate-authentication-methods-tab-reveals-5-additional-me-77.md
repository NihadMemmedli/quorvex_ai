# Test: Alternate authentication methods tab reveals 5 additional methods

## Description
Validates that the identity provider exposes 6 total authentication methods (1 default + 5 alternate) via the 'Digər üsullar' tab.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://mygovid.gov.az/auth
2. Verify the default QR code (mygov mobile app) authentication method is displayed
3. Click the 'Digər üsullar' tab
4. Inspect the revealed authentication method options

## Expected Outcome
- Default view shows QR code method for mygov mobile app
- After clicking 'Digər üsullar', 5 alternate methods are visible: SİMA İmza, Asan İmza, SİMA Token, Identification Number, BSXM Elektron İmza
- Total of 6 authentication methods are accessible across both tabs

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-071
- Source flow(s): Choose alternate authentication method
