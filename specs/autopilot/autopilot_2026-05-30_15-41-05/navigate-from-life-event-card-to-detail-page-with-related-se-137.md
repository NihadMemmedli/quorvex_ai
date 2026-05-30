# Test: Navigate from Life Event card to detail page with related services

## Description
Validates the full navigation path: Life Events listing → life event detail → service detail page, including breadcrumb navigation and related services links.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/lifeEvents
2. Click the 'Marriage - Ailə qurmaq' life event card
3. Verify navigation to /life-events/{uuid} with breadcrumb: Home > Life Events > Ailə qurmaq
4. Verify a descriptive paragraph about marriage procedures is displayed
5. Verify a 'Related services' section lists applicable e-services
6. Click the 'Nikahın qeydiyyata alınması üçün ərizə' (Marriage registration application) link
7. Verify navigation to /services/marriage-registration?serviceLabel=MR
8. Verify breadcrumb shows: Home > Services > {Entity Name} > Service Name
9. Verify service description, pricing table (20 AZN + 10 AZN), and 4-step process are displayed
10. Verify an 'Apply' button (MÜRACİƏT ET) is present
11. Verify a FAQ tab is available on the service detail page

## Expected Outcome
- Life event detail page loads with correct breadcrumb
- Related services section contains at least one clickable service link
- Service detail page loads with serviceLabel=MR query parameter
- Pricing table shows fees, numbered steps table describes the process
- Apply button is prominently displayed

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-122, REQ-123, REQ-135, REQ-136
- Source flow(s): Browse Life Event Services and Attempt to Apply
