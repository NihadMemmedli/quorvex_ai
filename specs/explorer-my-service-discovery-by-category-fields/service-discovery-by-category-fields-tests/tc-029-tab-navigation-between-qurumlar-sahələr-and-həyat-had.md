# Test: Tab Navigation Between Qurumlar, Sahələr, and Həyat Hadisələri

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-029
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
Verify that clicking the other tabs ("Qurumlar" and "Həyat hadisələri") on the services page changes the displayed content.

## Preconditions
- Browser on the service categories page.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Verify the "Sahələr" tab is selected by default
3. Click the "Qurumlar" tab using `getByRole('tab', { name: 'Qurumlar' })`
4. Verify the page content changes (shows institutions/entities instead of category cards)
5. Verify the "Qurumlar" tab is now selected
6. Click the "Həyat hadisələri" tab using `getByRole('tab', { name: 'Həyat hadisələri' })`
7. Verify the page content changes again (shows life events)
