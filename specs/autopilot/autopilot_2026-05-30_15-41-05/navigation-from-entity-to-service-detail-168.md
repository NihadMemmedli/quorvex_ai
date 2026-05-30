# Test: Navigation from Entity to Service Detail

## Description
The system shall allow users to navigate from a government entity detail page to individual service detail pages for each listed service.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Navigation from Entity to Service Detail

## Expected Outcome
- Entity detail page displays all services as cards with clickable links
- Clicking a service card navigates to its service detail page with the appropriate serviceLabel parameter
- Services include direct links for: birth registration (serviceLabel=BR), marriage registration (serviceLabel=MR), minor travel consent (serviceLabel=MTC), divorce application (serviceLabel=OAFD), adoption application (serviceLabel=OAFA), name change application (serviceLabel=OAFCSNP), death registration (serviceLabel=DCR)
- Each service card may also contain download (PDF) and video tutorial action buttons

## Test Data
- Target URL: https://my.gov.az/serviceCategories
