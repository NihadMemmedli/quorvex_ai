# Test: No Critical Console Errors on Categories and Service Pages

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-032
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
Verify that no critical JavaScript errors are present on the categories page, category detail, and service detail pages. Note: 404 API errors for custom-info and SEO endpoints are known non-blocking issues.

## Preconditions
- Browser console monitoring enabled.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Collect all console error messages
3. Verify no errors related to critical page functionality (rendering, navigation)
4. Note known non-blocking 404 errors: `/dg-mw-web/custom-info` and `/dg-mw-web/dg-catalog/api/v1/seo/by-label`
5. Navigate to a category detail page and repeat error check
6. Navigate to a service detail page and repeat error check
