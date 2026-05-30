# Test: Personal Information Access with Authentication Requirement

## Description
The system shall require mygov ID authentication before granting access to personal information pages (My Info section). Featured personal services on the home page must redirect unauthenticated users to the authentication platform.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Personal Information Access with Authentication Requirement

## Expected Outcome
- My Info section is accessible from the home page with links to: My fines (/my-info/cerimelerim/MF), Personal account info (/my-info/ferdi-sexsi-hesab-melumatlarim/MIPAI), Labor pension info (/my-info/emek-pensiyasi-uzre-melumatlarim/MYLPI)
- Clicking any personal information link when not authenticated redirects to https://mygovid.gov.az/auth
- After successful authentication, user is redirected back to the requested personal information page
- Personal information is only displayed after successful authentication

## Test Data
- Target URL: https://my.gov.az/serviceCategories
