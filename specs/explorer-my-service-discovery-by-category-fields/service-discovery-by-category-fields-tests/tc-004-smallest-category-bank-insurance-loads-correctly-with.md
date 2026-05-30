# Test: Smallest Category (Bank Insurance) Loads Correctly with 4 Services

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-004
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
Verify that the smallest category by service count (Bank insurance with 4 services) loads correctly and all services are listed.

## Preconditions
- Fresh browser session on the categories page.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Click the "Bank və Sığorta" category link using `getByRole('link', { name: /Bank və Sığorta/ })`
4. Verify the URL changes to /serviceCategories/dd3e62ee-fed3-4367-867a-8f3485405ac1
5. Verify the page heading shows "Bank və Sığorta" using `getByRole('heading', { name: 'Bank və Sığorta' })`
6. Verify exactly 4 service links are visible: | "İpoteka kreditinin verilməsi" | "Sahibkarlıq kreditlərinə zəmanətlərin verilməsi" | "Sığorta xidmətləri" | "Elektron kredit və zəmanət informasiya sistemi"
