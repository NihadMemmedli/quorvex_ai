# Test: Largest Category (Legal - 96 Services) Loads and All Services Visible

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-005
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
Verify that the largest category by service count (Legal/Hüquqi xidmətlər with 96 services) loads correctly and all services are accessible (possibly requiring scrolling).

## Preconditions
- Fresh browser session on the categories page.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Click the "Hüquqi xidmətlər" (Legal) category link using `getByRole('link', { name: /Hüquqi xidmətlər/ })`
4. Verify the URL changes to /serviceCategories/817e5af6-d733-4042-bd33-0cf80d0c8456
5. Verify the page heading shows "Hüquqi xidmətlər" using `getByRole('heading', { name: 'Hüquqi xidmətlər' })`
6. Scroll down to load all services if lazy-loaded
7. Count all service link elements and verify at least 96 are present
