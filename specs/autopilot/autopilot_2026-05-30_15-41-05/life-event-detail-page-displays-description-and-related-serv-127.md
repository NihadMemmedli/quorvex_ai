# Test: Life event detail page displays description and related services

## Description
Validates that clicking a life event card (e.g., Marriage) navigates to a detail page showing the life event description and a list of related government services with links to their detail pages.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/lifeEvents
2. Verify 11 life event cards are displayed
3. Click 'Marriage' life event card
4. Verify navigation to /life-events/{uuid}
5. Verify breadcrumb: Ana səhifə > Həyat hadisələri > [Life Event Name]
6. Verify life event description section is present
7. Verify related services section lists applicable government services
8. Click a related service link and verify it navigates to a service detail page

## Expected Outcome
- Life event detail page loads with correct breadcrumb
- Description content is rendered
- Related services are listed with clickable links to service detail pages
- Breadcrumb segments are clickable for back-navigation

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-097, REQ-098
- Source flow(s): Browse Services by Life Event
