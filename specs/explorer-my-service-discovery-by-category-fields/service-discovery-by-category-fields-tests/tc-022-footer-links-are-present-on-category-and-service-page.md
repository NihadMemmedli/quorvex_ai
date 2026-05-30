# Test: Footer Links Are Present on Category and Service Pages

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-022
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
Verify that the footer section with navigation links, social media links, and stats is present on both the categories listing and category detail pages.

## Preconditions
- Browser on the service categories page.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Scroll to the footer
3. Verify the following footer sections are present: | "Ana səhifə" section with "Haqqımızda" and "Xidmət təminatçıları" links | "Xidmətlər" section with "Həyat hadisələri", "Qurumlar", "Sahələr" links | "Resurslar" section with "Təlimatlar", "Normativ hüquqi sənədlər" links | "Media" section with "Xəbərlər" link | Social media links (Facebook, LinkedIn, Instagram, YouTube, Twitter, TikTok) | App store links (Google Play, App Store) | Stats counters (İstifadəçi sayı, Səhifə baxış sayı, Orta sərf olunan vaxt) | Copyright notice "Bütün hüquqlar qorunur - 2026"
