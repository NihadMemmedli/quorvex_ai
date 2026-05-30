# Test: Each Category Displays Correct Service Count

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-002
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
Verify that every category card shows the correct number of services as a badge or inline count.

## Preconditions
- Fresh browser session on the categories page.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. For each category card, verify the service count matches expected: | Sosial müdafiə: 16 | Təhsil: 27 | Səhiyyə: 23 | Rabitə xidmətləri: 18 | Online ödənişlər: 13 | Gömrük: 9 | Vergilər: 49 | Hüquqi xidmətlər: 96 | Xüsusi razılıq: 40 | Rəqəmsal İcra Hakimiyyəti: 11 | Arayışlar: 8 | Müraciətlər: 16 | Bank və Sığorta: 4 | Kommunal: 37 | Digər: 38
4. Verify that total services across all categories equals 387
