# Test: Personal information links redirect unauthenticated users to mygov ID

## Description
Validates that featured My Info links on the home page (My fines, Personal account info, Labor pension info) redirect unauthenticated users to https://mygovid.gov.az/auth.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/
2. Verify My Info section is present on the home page
3. Click 'Cərimələrim' (My fines) link
4. Verify redirect to https://mygovid.gov.az/auth
5. Navigate back to https://my.gov.az/
6. Click 'Əmək pensiyası üzrə məlumatlarım' (Labor pension info) link
7. Verify redirect to https://mygovid.gov.az/auth

## Expected Outcome
- My Info section is visible on the home page
- Each personal information link redirects unauthenticated users to mygov ID auth
- Redirect URL includes proper OAuth2 parameters

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-091, REQ-104
- Source flow(s): Access Personal Information (My Info)
