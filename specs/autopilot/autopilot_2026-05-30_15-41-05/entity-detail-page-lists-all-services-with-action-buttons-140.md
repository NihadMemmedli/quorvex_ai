# Test: Entity detail page lists all services with action buttons

## Description
Validates that clicking a government entity card loads its detail page with all e-services displayed, including specific civil registration services from Ministry of Justice.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities
2. Click the 'Ədliyyə Nazirliyi' (Ministry of Justice) entity card
3. Verify navigation to /entities/{uuid}
4. Verify breadcrumb shows: Home > Services > Ədliyyə Nazirliyi
5. Verify at least 29 services are listed in a grid
6. Verify services include: birth certificate, marriage registration, minor travel consent, online divorce, online adoption, name change, death certificate
7. Verify each service card shows an icon, service name, and action buttons (apply/download/video)
8. Click a service card and verify navigation to service detail page with serviceLabel parameter

## Expected Outcome
- Entity detail page loads with correct breadcrumb
- At least 29 service cards are displayed
- Key civil registration services are present (BR, MR, MTC, OAFD, OAFA, OAFCSNP, DCR)
- Each service card is clickable and navigates to /services/{service}?serviceLabel={label}

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-126, REQ-135, REQ-137
- Source flow(s): Browse Government Entity Services
