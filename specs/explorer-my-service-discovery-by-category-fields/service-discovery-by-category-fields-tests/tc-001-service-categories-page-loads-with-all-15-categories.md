# Test: Service Categories Page Loads with All 15 Categories

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-001
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
Verify that the /serviceCategories page loads successfully and displays all 15 expected service categories under the "Sahələr" tab.

## Preconditions
- Fresh browser session. No authentication required.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner by clicking the "Bağla" button if present
3. Verify the page heading "Xidmətlər" is visible using `getByRole('heading', { name: 'Xidmətlər' })`
4. Verify the "Sahələr" tab is selected using `getByRole('tab', { name: 'Sahələr' })`
5. Verify all 15 category links are visible: | `getByRole('link', { name: /Sosial müdafiə/ })` | `getByRole('link', { name: /Təhsil/ })` | `getByRole('link', { name: /Səhiyyə/ })` | `getByRole('link', { name: /Rabitə xidmətləri/ })` | `getByRole('link', { name: /Online ödənişlər/ })` | `getByRole('link', { name: /Gömrük/ })` | `getByRole('link', { name: /Vergilər/ })` | `getByRole('link', { name: /Hüquqi xidmətlər/ })` | `getByRole('link', { name: /Xüsusi razılıq/ })` | `getByRole('link', { name: /Rəqəmsal İcra/ })` | `getByRole('link', { name: /Arayışlar/ })` | `getByRole('link', { name: /Müraciətlər/ })` | `getByRole('link', { name: /Bank və Sığorta/ })` | `getByRole('link', { name: /Kommunal/ })` | `getByRole('link', { name: /Digər/ })`
6. Verify the breadcrumb shows "Ana səhifə / Xidmətlər"
