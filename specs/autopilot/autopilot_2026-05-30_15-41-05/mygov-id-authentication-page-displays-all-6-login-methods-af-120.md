# Test: mygov ID authentication page displays all 6 login methods after expanding

## Description
Validates that the mygov ID auth page shows QR code as default, and clicking 'Digər üsullar' reveals all 5 alternative methods: SIMA İmza, Asan İmza, SIMA Token, İdentifikasiya nömrəsi, BSXM Elektron İmza.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://mygovid.gov.az/auth
2. Verify QR code login is displayed as the primary/default method
3. Verify step-by-step QR code login instructions are visible
4. Click 'Digər üsullar' (Other methods) button
5. Verify 5 alternative methods are revealed: SIMA İmza, Asan İmza, SIMA Token (Elektron İmza), İdentifikasiya nömrəsi, BSXM Elektron İmza
6. Verify language selector (AZ/EN) is present
7. Verify security information panel about .gov.az domains and HTTPS is displayed

## Expected Outcome
- QR code is the default visible authentication option
- All 6 authentication methods are accessible (1 default + 5 alternatives)
- Language selector allows switching between AZ and EN
- Security trust information is visible on the page

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-096
- Source flow(s): Apply for Government Service, Navigation: service_categories to login (inferred)
