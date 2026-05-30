# Test: Full Happy Path Journey - Categories to Service Detail and Back

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-017
Category: Categories Observed (15 total)

## Scope
This test plan covers the "Sahələr" (Fields) tab on the Services page of my.gov.az. It validates browsing 15 service categories, navigating into category detail pages with service listings, viewing individual service detail pages, and interacting with regulation documents, e-gov links, and apply buttons. It includes happy path, navigation, edge case, accessibility, responsive, and API-backed scenarios.

## Observed Selectors
**Category listing page** (`/serviceCategories`):
- Tab: `getByRole('tab', { name: 'Sahələr' })` (selected by default)
- Category cards: `getByRole('link', { name: /Təhsil/ })` pattern for each category
- Service count badge: number inside the card next to category name

**Category detail page** (`/serviceCategories/{uuid}`):
- Page heading: `getByRole('heading', { name: 'Təhsil' })` (h6)
- Breadcrumb: navigation list with "Ana səhifə", "Xidmətlər", category name
- Service links: `getByRole('link', { name: 'Təhsil sənədlərinin hə...' })` pattern
- Action buttons per service: regulation doc, e-gov link, apply button (some disabled)
- "Yeni" badge on some new services

**Service detail page** (`/services/{slug}?serviceLabel={code}`):
- Page heading: `getByRole('heading', { name: /Təhsil sənədləri/ })` (h6)
- Tabs: `getByRole('tab', { name: 'Xidmətin təsviri' })`, `getByRole('tab', { name: 'Tez-tez verilən suallar' })`
- Apply button: `getByRole('button', { name: 'MÜRACİƏT ET' })`
- Breadcrumb: "Ana səhifə" > "Xidmətlər" > [Institution] > [Service name]

## Description
End-to-end happy path: Navigate from categories page → select a category → select a service → verify service detail → navigate back via breadcrumbs.

## Preconditions
- Fresh browser session. No authentication required.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Verify the "Sahələr" tab is selected
4. Click the "Vergilər" (Taxes) category link
5. Verify the URL changes to /serviceCategories/816adc1f-73bf-4ad6-8322-70e5a7332b28
6. Verify the heading "Vergilər" is visible
7. Click the "Ana səhifə" breadcrumb link
8. Verify navigation to the home page
