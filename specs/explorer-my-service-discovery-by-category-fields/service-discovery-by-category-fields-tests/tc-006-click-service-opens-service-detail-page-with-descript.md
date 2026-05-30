# Test: Click Service Opens Service Detail Page with Description and Apply Button

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-006
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
Verify that clicking a service link on a category detail page navigates to the service detail page, which shows the service description and an active "MÜRACİƏT ET" (Apply) button.

## Preconditions
- Browser on the Education category detail page (/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e).

## Steps

1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Click the service link "Təhsil sənədlərinin həqiqiliyinin onlayn yoxlanılması" using `getByRole('link', { name: /Təhsil sənədlərinin həqiqiliyinin/ })`
3. Verify the URL changes to /services/online-verification-of-educational-documents
4. Verify the page heading matches the service name using `getByRole('heading', { name: /Təhsil sənədlərinin həqiqiliyinin/ })`
5. Verify the "Xidmətin təsviri" tab is selected
6. Verify the service description text is visible
7. Verify the "MÜRACİƏT ET" button is visible using `getByRole('button', { name: 'MÜRACİƏT ET' })`
8. Verify the breadcrumb shows "Ana səhifə / Xidmətlər / [Institution] / [Service name]"
