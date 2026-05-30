# Test: Accessibility Menu Opens and Displays UserWay Options

## Source
Generated from: `service-discovery-by-category-fields.md`
Test ID: TC-028
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
Verify that the accessibility menu (UserWay widget) opens when clicking the "Müyəssərlik Menyusu" button and displays all accessibility options.

## Preconditions
- Browser on any page of my.gov.az.

## Steps

1. Navigate to https://my.gov.az/serviceCategories
2. Click the "Müyəssərlik Menyusu" button using `getByRole('button', { name: 'Müyəssərlik Menyusu' })`
3. Verify the accessibility dialog opens with heading "Müyəssərlik Menyusu (CTRL+U)"
4. Verify the following options are visible: | "Kontrast +" button | "Bağlantıları vurğulayın" (Highlight links) button | "Daha böyük mətn" (Larger text) button | "Mətn aralığını artırın" (Text spacing) button | "Animasiyalara fasilə verin" (Pause animations) button | "Şəkilləri gizlədin" (Hide images) button | "Disleksiya rejimi" (Dyslexia mode) button | "Kursor" (Cursor) button | "Xəttin hündürlüyünü artırın" (Line height) button
5. Verify the "Bütün Əlçatımlılıq Parametrlərini sıfırlayın" (Reset all) button is present
