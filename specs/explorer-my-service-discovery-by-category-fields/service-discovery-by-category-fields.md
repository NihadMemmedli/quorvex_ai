# Test Plan: Service Discovery by Category (Fields)

## Overview

**Application**: my.gov.az - Azerbaijan E-Government Services Portal
**Target URL**: https://my.gov.az/serviceCategories
**Expected End State**: /services/{service}
**Feature Under Test**: Service Discovery by Category (Sahələr / Fields tab)
**Date**: 2026-05-29

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

## Categories Observed (15 total)

| # | Category (Azerbaijani) | English | UUID | Services |
|---|---|---|---|---|
| 1 | Sosial müdafiə, sosial təminat | Social protection | 01e3a9be-3f99-41d7-b285-c5238edb4c2f | 16 |
| 2 | Təhsil | Education | b351aaee-ea98-44ff-a164-4f090b9fab3e | 27 |
| 3 | Səhiyyə | Medicine | ee5e6f3f-bdc3-4c77-b8db-b51822586d58 | 23 |
| 4 | Rabitə xidmətləri | Telecommunications | e32ce95b-9da1-438b-acad-7d002eeb5afb | 18 |
| 5 | Online ödənişlər | Online payments | 0ac776cd-813b-4145-8c2a-9e3a1ca882a2 | 13 |
| 6 | Gömrük | Customs | b7cc5e95-0fa0-4ba7-8585-d431b7164d09 | 9 |
| 7 | Vergilər | Taxes | 816adc1f-73bf-4ad6-8322-70e5a7332b28 | 49 |
| 8 | Hüquqi xidmətlər | Legal | 817e5af6-d733-4042-bd33-0cf80d0c8456 | 96 |
| 9 | Xüsusi razılıq (lisenziyaların) verilməsi | Licenses | e3168273-9422-4601-9ab7-8097c6d93be0 | 40 |
| 10 | Rəqəmsal İcra Hakimiyyəti | Digital executive power | 52f0ccb5-059a-4589-9777-e9f5208b4d91 | 11 |
| 11 | Arayışlar | Reference letters | dbd44cd7-b786-425d-9a9c-8c9b3f2a39ee | 8 |
| 12 | Müraciətlər | Contacts | f6b24c43-dba4-451c-a516-3d01bee283d4 | 16 |
| 13 | Bank və Sığorta | Bank insurance | dd3e62ee-fed3-4367-867a-8f3485405ac1 | 4 |
| 14 | Kommunal | Communal | 4337c2b3-bc53-429f-836a-4eccfe5484c8 | 37 |
| 15 | Digər | Other | 16396bf2-aca8-4ffb-b366-16bd91b6b01d | 38 |

---

### TC-001: Service Categories Page Loads with All 15 Categories

**Description**: Verify that the /serviceCategories page loads successfully and displays all 15 expected service categories under the "Sahələr" tab.

**Preconditions**: Fresh browser session. No authentication required.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner by clicking the "Bağla" button if present
3. Verify the page heading "Xidmətlər" is visible using `getByRole('heading', { name: 'Xidmətlər' })`
4. Verify the "Sahələr" tab is selected using `getByRole('tab', { name: 'Sahələr' })`
5. Verify all 15 category links are visible:
   - `getByRole('link', { name: /Sosial müdafiə/ })`
   - `getByRole('link', { name: /Təhsil/ })`
   - `getByRole('link', { name: /Səhiyyə/ })`
   - `getByRole('link', { name: /Rabitə xidmətləri/ })`
   - `getByRole('link', { name: /Online ödənişlər/ })`
   - `getByRole('link', { name: /Gömrük/ })`
   - `getByRole('link', { name: /Vergilər/ })`
   - `getByRole('link', { name: /Hüquqi xidmətlər/ })`
   - `getByRole('link', { name: /Xüsusi razılıq/ })`
   - `getByRole('link', { name: /Rəqəmsal İcra/ })`
   - `getByRole('link', { name: /Arayışlar/ })`
   - `getByRole('link', { name: /Müraciətlər/ })`
   - `getByRole('link', { name: /Bank və Sığorta/ })`
   - `getByRole('link', { name: /Kommunal/ })`
   - `getByRole('link', { name: /Digər/ })`
6. Verify the breadcrumb shows "Ana səhifə / Xidmətlər"

**Expected Result**: Page loads without errors. All 15 category cards are visible, each containing a category name and an icon. The "Sahələr" tab is in selected state. Breadcrumb navigation is correct.

**Test Data**: URL: https://my.gov.az/serviceCategories

---

### TC-002: Each Category Displays Correct Service Count

**Description**: Verify that every category card shows the correct number of services as a badge or inline count.

**Preconditions**: Fresh browser session on the categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. For each category card, verify the service count matches expected:
   - Sosial müdafiə: 16
   - Təhsil: 27
   - Səhiyyə: 23
   - Rabitə xidmətləri: 18
   - Online ödənişlər: 13
   - Gömrük: 9
   - Vergilər: 49
   - Hüquqi xidmətlər: 96
   - Xüsusi razılıq: 40
   - Rəqəmsal İcra Hakimiyyəti: 11
   - Arayışlar: 8
   - Müraciətlər: 16
   - Bank və Sığorta: 4
   - Kommunal: 37
   - Digər: 38
4. Verify that total services across all categories equals 387

**Expected Result**: Each category card displays the correct service count. The counts are visible and match the expected values listed above.

**Test Data**: Category UUIDs and expected counts as listed in the Categories Observed table.

---

### TC-003: Click Category Navigates to Category Detail with Service Listing

**Description**: Verify that clicking a category card navigates to the category detail page and displays the list of services for that category.

**Preconditions**: Fresh browser session on the categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Click the "Təhsil" (Education) category link using `getByRole('link', { name: /Təhsil/ })`
4. Verify the URL changes to /serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
5. Verify the page heading shows "Təhsil" using `getByRole('heading', { name: 'Təhsil' })`
6. Verify the breadcrumb shows "Ana səhifə / Xidmətlər / Təhsil"
7. Verify service links are visible (at least one service listed)
8. Count the service links and verify the count is 27

**Expected Result**: Clicking a category card navigates to its detail page. The URL contains the category UUID. The page heading matches the category name. Services are listed with links. The number of services matches the expected count.

**Test Data**: Category: Təhsil (Education), UUID: b351aaee-ea98-44ff-a164-4f090b9fab3e, Expected services: 27

---

### TC-004: Smallest Category (Bank Insurance) Loads Correctly with 4 Services

**Description**: Verify that the smallest category by service count (Bank insurance with 4 services) loads correctly and all services are listed.

**Preconditions**: Fresh browser session on the categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Click the "Bank və Sığorta" category link using `getByRole('link', { name: /Bank və Sığorta/ })`
4. Verify the URL changes to /serviceCategories/dd3e62ee-fed3-4367-867a-8f3485405ac1
5. Verify the page heading shows "Bank və Sığorta" using `getByRole('heading', { name: 'Bank və Sığorta' })`
6. Verify exactly 4 service links are visible:
   - "İpoteka kreditinin verilməsi"
   - "Sahibkarlıq kreditlərinə zəmanətlərin verilməsi"
   - "Sığorta xidmətləri"
   - "Elektron kredit və zəmanət informasiya sistemi"

**Expected Result**: Category detail page loads with heading "Bank və Sığorta". Exactly 4 services are listed. Each service has a visible name and icon.

**Test Data**: Category: Bank və Sığorta, UUID: dd3e62ee-fed3-4367-867a-8f3485405ac1, Expected services: 4

---

### TC-005: Largest Category (Legal - 96 Services) Loads and All Services Visible

**Description**: Verify that the largest category by service count (Legal/Hüquqi xidmətlər with 96 services) loads correctly and all services are accessible (possibly requiring scrolling).

**Preconditions**: Fresh browser session on the categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Click the "Hüquqi xidmətlər" (Legal) category link using `getByRole('link', { name: /Hüquqi xidmətlər/ })`
4. Verify the URL changes to /serviceCategories/817e5af6-d733-4042-bd33-0cf80d0c8456
5. Verify the page heading shows "Hüquqi xidmətlər" using `getByRole('heading', { name: 'Hüquqi xidmətlər' })`
6. Scroll down to load all services if lazy-loaded
7. Count all service link elements and verify at least 96 are present

**Expected Result**: Category detail page loads with the correct heading. All 96 services are listed (may require scrolling). No loading errors or timeouts.

**Test Data**: Category: Hüquqi xidmətlər, UUID: 817e5af6-d733-4042-bd33-0cf80d0c8456, Expected services: 96

---

### TC-006: Click Service Opens Service Detail Page with Description and Apply Button

**Description**: Verify that clicking a service link on a category detail page navigates to the service detail page, which shows the service description and an active "MÜRACİƏT ET" (Apply) button.

**Preconditions**: Browser on the Education category detail page (/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e).

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Click the service link "Təhsil sənədlərinin həqiqiliyinin onlayn yoxlanılması" using `getByRole('link', { name: /Təhsil sənədlərinin həqiqiliyinin/ })`
3. Verify the URL changes to /services/online-verification-of-educational-documents
4. Verify the page heading matches the service name using `getByRole('heading', { name: /Təhsil sənədlərinin həqiqiliyinin/ })`
5. Verify the "Xidmətin təsviri" tab is selected
6. Verify the service description text is visible
7. Verify the "MÜRACİƏT ET" button is visible using `getByRole('button', { name: 'MÜRACİƏT ET' })`
8. Verify the breadcrumb shows "Ana səhifə / Xidmətlər / [Institution] / [Service name]"

**Expected Result**: Service detail page loads with correct heading. Description section is visible. "MÜRACİƏT ET" button is present and not disabled. Breadcrumb includes the institution and service name.

**Test Data**: Service: Təhsil sənədlərinin həqiqiliyinin onlayn yoxlanılması, URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-007: Breadcrumb Navigation from Category Detail Back to Services

**Description**: Verify that the breadcrumb "Xidmətlər" link on a category detail page navigates back to the services listing page.

**Preconditions**: Browser on a category detail page (e.g., Təhsil).

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Verify the breadcrumb is visible with "Ana səhifə", "Xidmətlər", and "Təhsil" links
3. Click the "Xidmətlər" breadcrumb link using `getByRole('link', { name: 'Xidmətlər' })` in the breadcrumb navigation
4. Verify the page navigates to the services/entities page

**Expected Result**: Clicking the "Xidmətlər" breadcrumb link navigates away from the category detail page. The URL changes to reflect the services page.

**Test Data**: Start URL: /serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e

---

### TC-008: Breadcrumb Navigation from Service Detail Back to Institution

**Description**: Verify that the breadcrumb institution link on a service detail page navigates to the institution/entity page.

**Preconditions**: Browser on a service detail page.

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Verify the breadcrumb shows "Ana səhifə / Xidmətlər / [Institution] / [Service Name]"
3. Click the institution link in the breadcrumb (e.g., "Elm və Təhsil Nazirliyi")
4. Verify the page navigates to the entity page for that institution

**Expected Result**: Clicking the institution breadcrumb link navigates to the institution's entity page. The URL contains /entities/{uuid}.

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED, Expected institution: Elm və Təhsil Nazirliyi

---

### TC-009: Service with Disabled Regulation Document Button

**Description**: Verify that some services on the category detail page have disabled regulation document buttons, and these cannot be clicked.

**Preconditions**: Browser on the Education category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Find the service "Təhsil sənədlərinin həqiqiliyinin onlayn yoxlanılması"
3. Verify the first action button (regulation document) on this service card is disabled
4. Attempt to click the disabled regulation button and verify no navigation occurs

**Expected Result**: The regulation document button is in a disabled state (has `disabled` attribute). Clicking it does not trigger any navigation or action.

**Test Data**: Service: Təhsil sənədlərinin həqiqiliyinin onlayn yoxlanılması, Expected: regulation button disabled

---

### TC-010: Service with Active E-Gov Link Points to e-gov.az

**Description**: Verify that services with active e-gov link buttons correctly point to the e-gov.az domain.

**Preconditions**: Browser on the Education category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Find the service "Bakalavrların bakalavr pilləsinə qəbul olmaq üçün təqdim etdikləri ərizələrin iş nömrələrinin axtarışı"
3. Verify the second action button (e-gov link) is an active link
4. Verify the link href contains "e-gov.az"

**Expected Result**: The e-gov link button is an active link element. The href attribute points to a URL containing "e-gov.az" (e.g., https://e-gov.az//home/getfile/346).

**Test Data**: Service: Bakalavrların bakalavr pilləsinə qəbul olmaq..., Expected e-gov URL: https://e-gov.az//home/getfile/346

---

### TC-011: Service with Active External Apply Link

**Description**: Verify that a service with an active apply button on the category listing page links to the correct external URL.

**Preconditions**: Browser on the Bank insurance category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/dd3e62ee-fed3-4367-867a-8f3485405ac1
2. Find the service "Sahibkarlıq kreditlərinə zəmanətlərin verilməsi"
3. Verify the third action button (apply) is an active link (not disabled)
4. Verify the apply link href contains "mcgf.gov.az"

**Expected Result**: The apply button for this service is an active link element pointing to http://www.mcgf.gov.az/menu/196. The button is not disabled and can be clicked.

**Test Data**: Service: Sahibkarlıq kreditlərinə zəmanətlərin verilməsi, Expected apply URL: http://www.mcgf.gov.az/menu/196

---

### TC-012: Service with All Action Buttons Disabled

**Description**: Verify that some services have all three action buttons (regulation document, e-gov link, apply) disabled on the category listing page, but the detail page still shows an active apply button.

**Preconditions**: Browser on the Bank insurance category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/dd3e62ee-fed3-4367-867a-8f3485405ac1
2. Find the service "Elektron kredit və zəmanət informasiya sistemi"
3. Verify all three action buttons are disabled buttons (not links)
4. Click the service name link to navigate to the service detail page
5. Verify the service detail page still shows the "MÜRACİƏT ET" button (not disabled on detail page)

**Expected Result**: On the category listing page, all three action buttons for this service are disabled. However, on the service detail page, the "MÜRACİƏT ET" button is still active.

**Test Data**: Service: Elektron kredit və zəmanət informasiya sistemi, URL: /services/electronic-credit-and-guarantee-information-system?serviceLabel=ECAGIS

---

### TC-013: Service Detail Page Shows Empty Description Gracefully

**Description**: Verify that a service with no description text on the detail page still renders the page layout correctly without errors.

**Preconditions**: Browser on a service detail page known to have empty description.

**Steps**:
1. Navigate to https://my.gov.az/services/electronic-credit-and-guarantee-information-system?serviceLabel=ECAGIS
2. Verify the page heading "Elektron kredit və zəmanət informasiya sistemi" is visible
3. Verify the "Xidmətin təsviri" section is present (heading visible)
4. Verify no JavaScript errors occur due to the empty description
5. Verify the "MÜRACİƏT ET" button is still visible and clickable

**Expected Result**: The service detail page renders correctly even with an empty description. The heading and "MÜRACİƏT ET" button are visible. No JavaScript errors are triggered by the missing content.

**Test Data**: Service: Elektron kredit və zəmanət informasiya sistemi, URL: /services/electronic-credit-and-guarantee-information-system?serviceLabel=ECAGIS

---

### TC-014: Service Detail Tabs - Xidmətin Təsviri Tab Is Default

**Description**: Verify that the service detail page loads with the "Xidmətin təsviri" (Service description) tab selected by default.

**Preconditions**: Browser on a service detail page.

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Verify the tablist contains two tabs: "Xidmətin təsviri" and "Tez-tez verilən suallar"
3. Verify the "Xidmətin təsviri" tab is in selected state
4. Verify the service description content is visible below the tabs

**Expected Result**: Two tabs are visible. "Xidmətin təsviri" tab is selected by default. The description content panel is visible.

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-015: Tab Switching - FAQ Tab Navigates to Support Page

**Description**: Verify that clicking the "Tez-tez verilən suallar" (FAQ) tab on the service detail page triggers navigation to the support page (observed behavior).

**Preconditions**: Browser on a service detail page.

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Click the "Tez-tez verilən suallar" tab using `getByRole('tab', { name: 'Tez-tez verilən suallar' })`
3. Verify the page navigates (observed: redirects to /support)
4. Take a snapshot to confirm the destination page

**Expected Result**: Clicking the FAQ tab navigates to the support/FAQ page at /support. This is the observed behavior (the tab acts as a navigation link rather than an in-page tab switch).

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-016: Service with "Yeni" (New) Badge Displayed

**Description**: Verify that new services display a "Yeni" badge on the category listing page.

**Preconditions**: Browser on the Education category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Scroll down to find the service "Ali və orta ixtisas təhsil müəssisələrinə təhsilalanların qeydiyyatı"
3. Verify a "Yeni" badge is visible on this service card
4. Verify the service also has all three action buttons disabled

**Expected Result**: The "Yeni" badge is displayed on the service card. The badge is clearly visible and distinguishable from the service name.

**Test Data**: Service: Ali və orta ixtisas təhsil müəssisələrinə təhsilalanların qeydiyyatı, Expected badge: "Yeni"

---

### TC-017: Full Happy Path Journey - Categories to Service Detail and Back

**Description**: End-to-end happy path: Navigate from categories page → select a category → select a service → verify service detail → navigate back via breadcrumbs.

**Preconditions**: Fresh browser session. No authentication required.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Dismiss any notification banner if present
3. Verify the "Sahələr" tab is selected
4. Click the "Vergilər" (Taxes) category link
5. Verify the URL changes to /serviceCategories/816adc1f-73bf-4ad6-8322-70e5a7332b28
6. Verify the heading "Vergilər" is visible
7. Click the "Ana səhifə" breadcrumb link
8. Verify navigation to the home page

**Expected Result**: The complete journey from categories page to category detail to service listing works without errors. Breadcrumb navigation works correctly at each level. No page crashes or blocking errors.

**Test Data**: Category: Vergilər (Taxes), UUID: 816adc1f-73bf-4ad6-8322-70e5a7332b28

---

### TC-018: Direct URL Navigation to Category Detail Page

**Description**: Verify that navigating directly to a category detail URL (without first visiting the categories page) loads correctly.

**Preconditions**: Fresh browser session. No prior navigation.

**Steps**:
1. Open a new browser tab
2. Navigate directly to https://my.gov.az/serviceCategories/ee5e6f3f-bdc3-4c77-b8db-b51822586d58 (Medicine category)
3. Verify the page heading shows "Səhiyyə"
4. Verify service links are listed
5. Verify the breadcrumb is correct

**Expected Result**: Direct URL navigation loads the category detail page correctly. The heading, services, and breadcrumb all display as expected without needing to visit the parent categories page first.

**Test Data**: Category: Səhiyyə (Medicine), UUID: ee5e6f3f-bdc3-4c77-b8db-b51822586d58

---

### TC-019: Direct URL Navigation to Service Detail Page

**Description**: Verify that navigating directly to a service detail URL loads correctly.

**Preconditions**: Fresh browser session.

**Steps**:
1. Open a new browser tab
2. Navigate directly to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
3. Verify the page heading is visible
4. Verify the service description is displayed
5. Verify the "MÜRACİƏT ET" button is present

**Expected Result**: Direct URL navigation to the service detail page works. All elements (heading, description, apply button) are visible.

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-020: Invalid Category UUID Returns Error or Redirect

**Description**: Verify that navigating to a category detail page with an invalid UUID handles the error gracefully.

**Preconditions**: Fresh browser session.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/00000000-0000-0000-0000-000000000000
2. Verify the page does not crash
3. Verify either an error message, empty state, or redirect is shown
4. Verify the header and footer still render correctly

**Expected Result**: The page handles the invalid UUID gracefully. Either a 404 page, empty category listing, or redirect occurs. The main page layout (header, footer) remains intact.

**Test Data**: Invalid UUID: 00000000-0000-0000-0000-000000000000

---

### TC-021: Regulation Document Link Points to External Resource

**Description**: Verify that services with active regulation document buttons link to valid external resources (e.g., huquqiaktlar.gov.az or edu.gov.az).

**Preconditions**: Browser on the Education category detail page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories/b351aaee-ea98-44ff-a164-4f090b9fab3e
2. Find the service "Xarici dövlətlərin ali təhsil sahəsində ixtisaslarının tanınması"
3. Verify the regulation document link is active (not disabled)
4. Verify the href contains "portal.edu.az" or "huquqiaktlar.gov.az"

**Expected Result**: The regulation document button is an active link pointing to an external document URL. The URL is a valid external domain.

**Test Data**: Service: Xarici dövlətlərin ali təhsil sahəsində..., Expected regulation URL: http://portal.edu.az/upload/_private3/4/reqlament.docx

---

### TC-022: Footer Links Are Present on Category and Service Pages

**Description**: Verify that the footer section with navigation links, social media links, and stats is present on both the categories listing and category detail pages.

**Preconditions**: Browser on the service categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Scroll to the footer
3. Verify the following footer sections are present:
   - "Ana səhifə" section with "Haqqımızda" and "Xidmət təminatçıları" links
   - "Xidmətlər" section with "Həyat hadisələri", "Qurumlar", "Sahələr" links
   - "Resurslar" section with "Təlimatlar", "Normativ hüquqi sənədlər" links
   - "Media" section with "Xəbərlər" link
   - Social media links (Facebook, LinkedIn, Instagram, YouTube, Twitter, TikTok)
   - App store links (Google Play, App Store)
   - Stats counters (İstifadəçi sayı, Səhifə baxış sayı, Orta sərf olunan vaxt)
   - Copyright notice "Bütün hüquqlar qorunur - 2026"

**Expected Result**: All footer sections and links are visible and correctly structured on the categories page.

**Test Data**: N/A

---

### TC-023: Responsive Layout on Mobile Viewport - Categories Page

**Description**: Verify that the categories page renders correctly on a mobile viewport (375x812) with all 15 categories accessible.

**Preconditions**: Browser viewport set to 375x812 (iPhone X size).

**Steps**:
1. Set browser viewport to 375x812
2. Navigate to https://my.gov.az/serviceCategories
3. Dismiss any notification banner if present
4. Verify all 15 category links are visible
5. Verify service counts are displayed inline in format "(16)" for each category
6. Verify the tablist ("Qurumlar", "Sahələr", "Həyat hadisələri") is still accessible
7. Scroll down and verify the footer is reachable

**Expected Result**: All 15 categories are displayed in a responsive layout. Category cards show service counts inline. Tab navigation remains accessible. Footer is reachable by scrolling.

**Test Data**: Viewport: 375x812 (iPhone X)

---

### TC-024: Responsive Layout on Mobile - Category Detail with Services

**Description**: Verify that a category detail page with services renders correctly on a mobile viewport.

**Preconditions**: Browser viewport set to 375x812.

**Steps**:
1. Set browser viewport to 375x812
2. Navigate to https://my.gov.az/serviceCategories/dd3e62ee-fed3-4367-867a-8f3485405ac1 (Bank insurance - small category)
3. Verify the heading "Bank və Sığorta" is visible
4. Verify all 4 service links are visible
5. Verify action buttons (regulation, e-gov, apply) are accessible on each service card

**Expected Result**: Category detail page renders responsively. Service cards stack vertically. Action buttons remain accessible. No horizontal scroll or overflow issues.

**Test Data**: Category: Bank və Sığorta, Viewport: 375x812

---

### TC-025: Accessibility - Heading Structure on Categories Page

**Description**: Verify the heading hierarchy on the service categories page follows accessibility best practices.

**Preconditions**: Browser on the service categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Verify the page has a heading structure:
   - h6 "Xidmətlər" as the main page heading
   - h2 headings in the footer ("Ana səhifə", "Xidmətlər", "Resurslar", "Media")
3. Verify the tablist uses proper ARIA tablist/tab roles
4. Verify the "Sahələr" tab has `selected` state

**Expected Result**: Heading structure is logical and sequential. Tab roles use proper ARIA attributes. The selected tab is correctly identified.

**Test Data**: N/A

---

### TC-026: Accessibility - Category Links Have Descriptive Accessible Names

**Description**: Verify that all category links have descriptive accessible names that include both the English and Azerbaijani names.

**Preconditions**: Browser on the service categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. For each category link, verify the accessible name includes descriptive text:
   - The link for Education should have accessible name containing "Education" and "Təhsil"
   - Each link should have an img with alt text matching the English category name
3. Verify all category links have `cursor: pointer` style (are clickable)

**Expected Result**: Each category link has a descriptive accessible name combining English and Azerbaijani text. Each has an icon image with appropriate alt text.

**Test Data**: N/A

---

### TC-027: Accessibility - Service Detail Page Keyboard Navigation

**Description**: Verify that the service detail page is navigable by keyboard, with focusable elements in logical order.

**Preconditions**: Browser on a service detail page.

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Press Tab key repeatedly to cycle through interactive elements
3. Verify the tab order includes: header links, breadcrumb links, tabs, "MÜRACİƏT ET" button, sidebar links, footer links
4. Verify focus indicators are visible on all focused elements
5. Verify pressing Enter on the "MÜRACİƏT ET" button triggers the apply action

**Expected Result**: All interactive elements are reachable via keyboard Tab navigation. Focus indicators are visible. Tab order is logical (top to bottom, left to right).

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-028: Accessibility Menu Opens and Displays UserWay Options

**Description**: Verify that the accessibility menu (UserWay widget) opens when clicking the "Müyəssərlik Menyusu" button and displays all accessibility options.

**Preconditions**: Browser on any page of my.gov.az.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Click the "Müyəssərlik Menyusu" button using `getByRole('button', { name: 'Müyəssərlik Menyusu' })`
3. Verify the accessibility dialog opens with heading "Müyəssərlik Menyusu (CTRL+U)"
4. Verify the following options are visible:
   - "Kontrast +" button
   - "Bağlantıları vurğulayın" (Highlight links) button
   - "Daha böyük mətn" (Larger text) button
   - "Mətn aralığını artırın" (Text spacing) button
   - "Animasiyalara fasilə verin" (Pause animations) button
   - "Şəkilləri gizlədin" (Hide images) button
   - "Disleksiya rejimi" (Dyslexia mode) button
   - "Kursor" (Cursor) button
   - "Xəttin hündürlüyünü artırın" (Line height) button
5. Verify the "Bütün Əlçatımlılıq Parametrlərini sıfırlayın" (Reset all) button is present

**Expected Result**: Accessibility menu opens with all expected options. The dialog is keyboard-accessible. Reset button is present.

**Test Data**: N/A

---

### TC-029: Tab Navigation Between Qurumlar, Sahələr, and Həyat Hadisələri

**Description**: Verify that clicking the other tabs ("Qurumlar" and "Həyat hadisələri") on the services page changes the displayed content.

**Preconditions**: Browser on the service categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Verify the "Sahələr" tab is selected by default
3. Click the "Qurumlar" tab using `getByRole('tab', { name: 'Qurumlar' })`
4. Verify the page content changes (shows institutions/entities instead of category cards)
5. Verify the "Qurumlar" tab is now selected
6. Click the "Həyat hadisələri" tab using `getByRole('tab', { name: 'Həyat hadisələri' })`
7. Verify the page content changes again (shows life events)

**Expected Result**: Clicking each tab changes the displayed content. The selected tab state updates correctly. Content for each tab is visible and distinct.

**Test Data**: N/A

---

### TC-030: Notification Banner Dismissal

**Description**: Verify that the maintenance notification banner can be dismissed and stays dismissed.

**Preconditions**: Fresh browser session.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. If a notification banner is visible (e.g., "Planlı təkmilləşdirmə işləri"), locate the "Bağla" button
3. Click the "Bağla" button using `getByRole('button', { name: 'Bağla' })`
4. Verify the banner is no longer visible
5. Reload the page and verify the banner does not reappear (may depend on session/localStorage)

**Expected Result**: Clicking the dismiss button removes the notification banner. The banner stays dismissed on page reload within the same session.

**Test Data**: Banner text observed: "28-29 may tarixlərində aparılan texniki yenilənmə işləri ilə əlaqədar xidmətlərdə müvəqqəti dayanmalar mümkündür."

---

### TC-031: Page Update Date Is Displayed

**Description**: Verify that each category page and service detail page displays the "Səhifənin son yenilənmə tarixi" (Last page update date) at the bottom of the content area.

**Preconditions**: Browser on the service categories page.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Scroll to the bottom of the content area (above the footer)
3. Verify the text "Səhifənin son yenilənmə tarixi:" is visible
4. Verify a date value (e.g., "12.03.2025") is displayed next to it
5. Navigate to a category detail page and verify the same date field is present

**Expected Result**: The last update date is visible on both the categories listing and category detail pages. The date follows the DD.MM.YYYY format.

**Test Data**: Expected date format: DD.MM.YYYY (observed: 12.03.2025)

---

### TC-032: No Critical Console Errors on Categories and Service Pages

**Description**: Verify that no critical JavaScript errors are present on the categories page, category detail, and service detail pages. Note: 404 API errors for custom-info and SEO endpoints are known non-blocking issues.

**Preconditions**: Browser console monitoring enabled.

**Steps**:
1. Navigate to https://my.gov.az/serviceCategories
2. Collect all console error messages
3. Verify no errors related to critical page functionality (rendering, navigation)
4. Note known non-blocking 404 errors: `/dg-mw-web/custom-info` and `/dg-mw-web/dg-catalog/api/v1/seo/by-label`
5. Navigate to a category detail page and repeat error check
6. Navigate to a service detail page and repeat error check

**Expected Result**: No critical JavaScript errors that prevent page rendering or navigation. Known 404 API errors for custom-info and SEO endpoints are acceptable as they do not block user interactions.

**Test Data**: Known non-blocking errors:
- 404 on https://mygov-apigw.e-gov.az/dg-mw-web/custom-info
- 404 on https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/seo/by-label?label=/serviceCategories

---

### TC-033: Apply Button on Service Detail Page Is Visible and Clickable

**Description**: Verify that the "MÜRACİƏT ET" (Apply) button on the service detail page is visible, not disabled, and attempts to initiate the application flow (likely requiring authentication).

**Preconditions**: Browser on a service detail page. Not authenticated.

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Verify the "MÜRACİƏT ET" button is visible using `getByRole('button', { name: 'MÜRACİƏT ET' })`
3. Verify the button is NOT disabled (no disabled attribute)
4. Click the "MÜRACİƏT ET" button
5. Verify that a login prompt, authentication redirect, or modal appears (expected behavior for unauthenticated users)

**Expected Result**: The "MÜRACİƏT ET" button is visible, enabled, and clickable. Clicking it triggers an authentication flow (login redirect or modal) since the user is not authenticated.

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED

---

### TC-034: Sidebar Quick Navigation on Service Detail Page

**Description**: Verify that the sidebar on the service detail page contains a "MÜRACİƏT ET" button and a navigation list with "Xidmətin təsviri" entry.

**Preconditions**: Browser on a service detail page (desktop viewport).

**Steps**:
1. Navigate to https://my.gov.az/services/online-verification-of-educational-documents?serviceLabel=OVOED
2. Verify a sidebar section is visible with a "MÜRACİƏT ET" button
3. Verify the sidebar contains a list with the item "Xidmətin təsviri"
4. Click the "Xidmətin təsviri" item in the sidebar and verify it scrolls or focuses the description section

**Expected Result**: Sidebar is visible with the apply button and navigation list. The "Xidmətin təsviri" item in the sidebar provides quick navigation to the description section.

**Test Data**: Service URL: /services/online-verification-of-educational-documents?serviceLabel=OVOED