# Test: Organization page displays 28 agencies and navigates to agency services

## Description
Validates that the Organizations page lists 28 government agencies with logos and service counts, and clicking an agency navigates to its filtered service list.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities
2. Verify Qurumlar tab is selected
3. Count and verify 28 organization cards are displayed
4. Verify each card has an agency logo and service count
5. Click an organization card (e.g., Ministry of Labour showing 35 services)
6. Verify navigation to /entities/{uuid} with filtered service list
7. Verify services displayed belong to the selected organization

## Expected Outcome
- 28 organization cards are rendered with logos and service counts
- Clicking an agency navigates to its service list page
- Filtered service list shows only services from the selected organization

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-099
- Source flow(s): Browse Services by Organization
