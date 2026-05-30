# Test: Life Event Detail Page with Related Services

## Description
The system shall display a detail page for each life event showing a description of the life process and listing all related government services with direct links.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Life Event Detail Page with Related Services

## Expected Outcome
- Life event detail page loads at /life-events/{uuid}
- Breadcrumb shows: Ana səhifə > Həyat hadisələri > [Life Event Name]
- Life event description section provides detailed information about the process (e.g., marriage legal registration, document preparation)
- Related services section lists all government services applicable to the life event
- Each related service links to its service detail page (e.g., /services/marriage-registration?serviceLabel=MR)
- Instruction PDF links from e-gov.az are available where applicable
- User can navigate back to the life events list via breadcrumb

## Test Data
- Target URL: https://my.gov.az/serviceCategories
