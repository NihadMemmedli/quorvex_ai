# Test: Login prompt modal appears on Apply click without page navigation

## Description
Validates that clicking MÜRACİƏT ET as an unauthenticated user triggers an inline modal overlay (not a page redirect), displaying 'Hesaba daxil olun!' heading and DAXİL OLUN button, while the page URL remains unchanged.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/services/retirement-calculator?serviceLabel=RC
2. Click the MÜRACİƏT ET (Apply) button
3. Verify a modal overlay appears with heading 'Hesaba daxil olun!'
4. Verify informational text about mygov ID login is displayed
5. Verify DAXİL OLUN (Login) button is present inside the modal
6. Verify the page URL has NOT changed (still /services/retirement-calculator?serviceLabel=RC)

## Expected Outcome
- Modal appears without any page navigation (URL unchanged)
- Modal contains 'Hesaba daxil olun!' heading and 'Log in via mygov ID' message
- DAXİL OLUN button is visible inside the modal

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-095, REQ-120
- Source flow(s): Apply for Government Service, Navigation: service_categories to login (inferred)
