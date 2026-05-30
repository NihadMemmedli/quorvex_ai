# Test: Navigate from service category to service detail page with Apply button

## Description
Validates the full navigation from category list → service detail page, confirming breadcrumb, description/FAQ tabs, MÜRACİƏT ET button, and electronic signature badges are rendered.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Click 'Sosial müdafiə, sosial təminat' category
3. Click 'Pensiya kalkulyatoru' (Pension Calculator) service link
4. Verify service detail page loads at /services/retirement-calculator?serviceLabel=RC
5. Verify breadcrumb: Ana səhifə > Xidmətlər > [Ministry] > Pensiya kalkulyatoru
6. Verify 'Xidmətin təsviri' (description) and 'Tez-tez verilən suallar' (FAQ) tabs are present
7. Verify MÜRACİƏT ET (Apply) button is displayed
8. Verify e-signature requirement badges are shown on applicable services

## Expected Outcome
- Service detail page loads with correct serviceLabel parameter
- Breadcrumb hierarchy is correct with clickable segments
- Both description and FAQ tabs are present and switchable
- Apply button is prominently visible on the page

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-094, REQ-095, REQ-119
- Source flow(s): Apply for Government Service, Navigation: service_categories to login (inferred)
