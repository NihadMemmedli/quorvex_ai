# Test Plan: Homepage Navigation and Service Discovery

## Overview

**Application**: my.gov.az - Azerbaijan E-Government Services Portal
**Target URL**: https://my.gov.az/
**Expected End State**: https://my.gov.az/az/services
**Feature Under Test**: Homepage Navigation and Service Discovery
**Date**: 2026-05-13

## Scope

This test plan covers all user interactions related to landing on the homepage, viewing featured services, navigating to the full services catalog, browsing service categories, filtering by category, and verifying service listings. It includes happy path, edge case, error handling, language toggle, and accessibility scenarios.

---

### TC-001: Homepage Loads Successfully Within 5 Seconds

**Description**: Verify that the my.gov.az homepage loads fully within the acceptable 5-second performance threshold.

**Preconditions**: Fresh browser session with cleared cache and cookies. Stable internet connection.

**Steps**:
1. Open a new browser window/tab.
2. Record the start timestamp.
3. Navigate to https://my.gov.az/.
4. Wait for the page to reach the "load" event (DOMContentLoaded + all resources).
5. Record the end timestamp and calculate total load time.
6. Take a snapshot of the fully loaded page.
7. Verify the main heading or hero section is visible.

**Expected Result**: Page loads fully within 5000 milliseconds. The homepage header, navigation bar, hero/banner section, and featured services grid are all rendered and visible. No JavaScript console errors related to critical resources.

---

### TC-002: Homepage Hero/Banner Section Is Visible

**Description**: Verify the hero/banner section on the homepage is rendered and contains expected branding elements.

**Preconditions**: Fresh browser session.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Verify the main logo or government branding is visible in the header.
4. Verify the hero/banner area contains a headline or call-to-action text.
5. Verify the page title in the browser tab matches the expected value (e.g., "my.gov.az").

**Expected Result**: The logo and government branding are visible. The hero section is rendered with at least one prominent heading or welcome message. Browser tab title is non-empty and references the portal name.

---

### TC-003: Navigation Menu Is Present and Displays All Top-Level Links

**Description**: Verify the main navigation menu is displayed and contains all expected top-level navigation items.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Locate the primary navigation bar using `getByRole('navigation')`.
4. Verify the navigation contains a link or button with text corresponding to "Xidmetler" (Services) or equivalent in the active language via `getByRole('link', { name: /xidm/i })`.
5. Verify additional navigation items such as "Haqqinda" (About) or news/announcements links are present.
6. Hover over any dropdown navigation items to verify submenus appear if applicable.

**Expected Result**: The main navigation bar is visible at the top of the page. At least a "Services" navigation link is present. Dropdown submenus (if any) appear on hover without errors.

---

### TC-004: Featured Services Section Displays Services With Count Greater Than Zero

**Description**: Verify that the featured/popular services section on the homepage displays at least one service card.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Scroll down to locate the "Featured Services" or "Popular Services" section.
4. Count the number of service cards/tiles rendered in that section.
5. Verify each service card contains at minimum: a service name/title and a clickable link.

**Expected Result**: The featured services section is visible. The count of service cards is greater than 0. Each service card has a visible title and is clickable.

---

### TC-005: "All Services" Button/Link Is Visible on Homepage

**Description**: Verify that a clearly labeled "All Services" or equivalent link is present on the homepage.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Scroll through the entire homepage to locate a "Butun xidmetler" (All Services) button/link using `getByText('Butun xidmetler')` or `getByRole('link', { name: /butun/i })`.
4. Verify the element is visible and not hidden.
5. Verify the element has a meaningful, non-empty text label.

**Expected Result**: An "All Services" or equivalent navigation element is visible on the homepage. The element is not disabled or hidden. The element text is readable.

---

### TC-006: Clicking "All Services" Navigates to Services Catalog Page

**Description**: Verify that clicking the "All Services" link from the homepage navigates to https://my.gov.az/az/services.

**Preconditions**: Browser navigated to https://my.gov.az/. The "All Services" link is visible.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot to confirm the homepage loaded.
3. Locate the "All Services" button or link using `getByText('Butun xidmetler')` or `getByRole('link', { name: /all services/i })`.
4. Click the located element.
5. Wait for navigation to complete.
6. Take a browser snapshot of the resulting page.
7. Verify the current URL is https://my.gov.az/az/services (or language-equivalent path).
8. Verify the services catalog page heading is visible.

**Expected Result**: Clicking "All Services" navigates to the services catalog page. The URL changes to https://my.gov.az/az/services or equivalent. The services catalog page renders with a heading and at least one service category or service listing. No 404 or error page is shown.

---

### TC-007: Services Catalog Page Displays Service Categories

**Description**: Verify the services catalog page at /az/services displays a list of service categories for filtering.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Locate the category filter panel or sidebar.
4. Count the number of distinct category items rendered.
5. Verify each category item has a visible label/name.
6. Verify categories are clickable (role="button" or role="link").

**Expected Result**: The services catalog page renders a list of service categories. At least 2 distinct category items are visible. Each category has a visible text label. Categories are interactive (clickable).

---

### TC-008: Selecting a Service Category Filters the Services List

**Description**: Verify that clicking a service category in the catalog filters the displayed services.

**Preconditions**: Browser navigated to https://my.gov.az/az/services. At least one category is visible.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot and note the total number of service items initially displayed.
3. Locate the first visible category item in the filter panel.
4. Note the category name.
5. Click the category item using `getByRole('button', { name: <category_name> })` or equivalent.
6. Wait for the page to update (wait for network idle or DOM update).
7. Take a browser snapshot after filtering.
8. Count the service items now displayed.
9. Verify the displayed services are related to the selected category.

**Expected Result**: After clicking a category, the services list updates to show only services in that category. The selected category appears visually highlighted/selected. Services in the list correspond to the selected category.

---

### TC-009: Services List on Catalog Page Has Count Greater Than Zero

**Description**: Verify that the services catalog page displays at least one service when loaded without filters.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Scroll through the page to locate the service cards/list items.
4. Count the total number of service items rendered.
5. Verify each service item has a visible name.

**Expected Result**: The services catalog page displays at least 1 service item. Service items are visible and have non-empty names. No "No services found" empty-state message is shown when loading the unfiltered catalog.

---

### TC-010: Individual Service Card on Catalog Page Has Required Information

**Description**: Verify that each service card in the catalog displays the minimum required information.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Locate the first service card in the list.
4. Verify the service card contains a non-empty service name/title.
5. Verify the service card contains a link or button to access the service.
6. Optionally verify if a category label or icon is present on the card.

**Expected Result**: Each service card has a non-empty service name. Each service card has a clickable element (link or button) leading to the service detail or application page. No service card is rendered with only placeholder/empty text.

---

### TC-011: Language Toggle Is Visible on Homepage

**Description**: Verify that the language selection control is visible and accessible on the homepage.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Locate the language toggle in the header area.
4. Verify it displays the available languages (e.g., "AZ", "RU", "EN").
5. Verify the current active language is visually distinguished (highlighted, underlined, or bold).

**Expected Result**: A language switcher control is visible in the header. It shows at least two language options. The currently active language is visually indicated.

---

### TC-012: Language Toggle Switches Page Language from Azerbaijani to Russian

**Description**: Verify that clicking the Russian language option switches the page content to Russian.

**Preconditions**: Browser navigated to https://my.gov.az/. Page is in Azerbaijani (AZ) by default.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot and note the page language is Azerbaijani.
3. Locate the language toggle in the header.
4. Click the "RU" (Russian) language option using `getByText('RU')` or `getByRole('button', { name: 'RU' })`.
5. Wait for the page to reload or content to update.
6. Take a browser snapshot after language switch.
7. Verify the page URL has changed to reflect the Russian language (e.g., /ru/ path prefix).
8. Verify the navigation menu items are now displayed in Russian (e.g., "Uslugi" instead of "Xidmetler").

**Expected Result**: Clicking the Russian language option changes the page content to Russian. The URL reflects the language change. Navigation text, headings, and button labels are displayed in Russian. The Russian language option is now highlighted as active.

---

### TC-013: Language Toggle Switches Page Language from Azerbaijani to English

**Description**: Verify that clicking the English language option switches the page content to English.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot to confirm default language (AZ).
3. Locate and click the "EN" language option using `getByText('EN')` or `getByRole('button', { name: 'EN' })`.
4. Wait for page update/reload.
5. Take a browser snapshot.
6. Verify page URL reflects English language (e.g., /en/ path).
7. Verify navigation menu text is now in English (e.g., "Services" instead of "Xidmetler").

**Expected Result**: Clicking EN switches the page to English. URL changes to English path variant. UI text including navigation, headings, and labels appears in English. EN is highlighted as the active language.

---

### TC-014: Language Switch Persists When Navigating from Homepage to Services Page

**Description**: Verify that the selected language persists when navigating from the homepage to the services catalog page.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Click the "RU" language option to switch to Russian.
3. Wait for the page to update to Russian.
4. Take a browser snapshot confirming Russian is active.
5. Locate and click the "All Services" / "Uslugi" link.
6. Wait for navigation to the services catalog page.
7. Take a browser snapshot of the services catalog page.
8. Verify the current URL contains the "ru" language segment (e.g., https://my.gov.az/ru/services).
9. Verify the services catalog page content is in Russian.

**Expected Result**: The Russian language persists after navigation from the homepage to the services catalog. The URL for the services page reflects the Russian language (/ru/services). Service category names, headings, and button labels on the services page are in Russian.

---

### TC-015: Language Toggle on Services Page Keeps User on Services Page

**Description**: Verify that switching language on the services catalog page does not redirect the user to the homepage.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Scroll down to verify services are loaded.
4. Locate the language toggle in the header.
5. Click the "EN" language option.
6. Wait for page reload/update.
7. Take a browser snapshot.
8. Verify the URL changes to the English equivalent of the services page (e.g., https://my.gov.az/en/services).
9. Verify the services catalog is still displayed (not redirected to homepage).

**Expected Result**: After toggling language on the services page, the user stays on the services page. URL changes to the language-equivalent path for services. Services list is still visible in the new language. User is not unexpectedly redirected to the homepage or an error page.

---

### TC-016: Search/Filter Input on Services Page Filters Correctly

**Description**: Verify that if a search or text filter input is present on the services catalog page, it correctly filters services by name.

**Preconditions**: Browser navigated to https://my.gov.az/az/services. A search input field is visible.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot and verify a search/filter input field is present.
3. Click on the search input field using `getByRole('searchbox')` or `getByPlaceholder(...)`.
4. Type a common service-related keyword (e.g., "pasport" or "sexsiyyet").
5. Wait for the results to update (real-time filtering or after pressing Enter).
6. Take a browser snapshot.
7. Verify the displayed service list is narrowed to results matching the search term.
8. Clear the search field (press Ctrl+A then Delete, or click a clear button).
9. Verify the full service list is restored.

**Expected Result**: Typing in the search field filters the services list. Only services matching the typed keyword are displayed. Clearing the search field restores all services. The search is case-insensitive.

---

### TC-017: Empty State Shown When No Services Match Filter

**Description**: Verify that if a filter returns no services, an appropriate empty state message is displayed.

**Preconditions**: Browser navigated to https://my.gov.az/az/services. A search field is present.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Type a nonsense non-matching search term in the search field (e.g., "xxxxxxxxxxx").
4. Wait for the results to update.
5. Take a browser snapshot.
6. Verify an empty state message is displayed (e.g., "Xidmet tapilmadi" / "No services found").
7. Verify the empty state message is meaningful (not a raw error, blank screen, or indefinite spinner).

**Expected Result**: When no services match the filter/search, an empty state message is displayed. The message is human-readable and in the current language. No JavaScript errors or blank page states occur. The search field or category filter remains visible so the user can modify their selection.

---

### TC-018: Category Page Does Not Show Loading Spinner Indefinitely on API Error

**Description**: Verify that if the services API is slow or fails, the page does not display an indefinite loading spinner.

**Preconditions**: Browser navigated to https://my.gov.az/az/services. Network throttling may be required.

**Steps**:
1. Navigate to https://my.gov.az/az/services using a throttled or offline network connection.
2. Attempt to click a category filter item.
3. Observe the page behavior while the network request is pending or fails.
4. Wait for at least 15 seconds.
5. Take a browser snapshot.
6. Verify the page does not remain frozen on a loading spinner indefinitely.
7. Verify an error message or retry option is presented to the user.

**Expected Result**: If the API fails, a user-friendly error message is displayed. A retry button or instructions to try again are provided. The page does not hang indefinitely. The user can still navigate away or retry.

---

### TC-019: Breadcrumb Navigation on Services Page

**Description**: Verify that breadcrumb navigation is displayed on the services catalog page and correctly reflects the navigation path.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Locate the breadcrumb navigation element near the top of the main content area using `getByRole('navigation', { name: /breadcrumb/i })` or similar.
4. Verify the breadcrumb contains at least two items: "Home" / "Ana sehife" and "Services" / "Xidmetler".
5. Click the "Home" breadcrumb link.
6. Verify navigation returns to https://my.gov.az/ (homepage).

**Expected Result**: A breadcrumb trail is visible on the services catalog page. The breadcrumb correctly shows "Home > Services" path. Clicking the "Home" breadcrumb navigates back to the homepage. The homepage loads correctly from the breadcrumb click.

---

### TC-020: Back Navigation from Services Page to Homepage

**Description**: Verify that the browser back button correctly navigates from the services catalog page back to the homepage.

**Preconditions**: Browser session starting at https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot to confirm the homepage is loaded.
3. Click the "All Services" link to navigate to https://my.gov.az/az/services.
4. Wait for the services page to fully load.
5. Take a browser snapshot confirming the services page is loaded.
6. Click the browser back button (or use `browser_navigate_back`).
7. Wait for navigation to complete.
8. Take a browser snapshot.
9. Verify the URL is back to https://my.gov.az/.
10. Verify the homepage content (hero/banner, featured services) is visible.

**Expected Result**: Clicking back from the services page returns the user to the homepage. The homepage is fully rendered with hero, navigation, and featured services visible. No broken state or empty page is shown after back navigation.

---

### TC-021: Homepage Featured Service Card Navigation to Service Detail

**Description**: Verify that clicking a featured service card on the homepage navigates to the correct service detail or application page.

**Preconditions**: Browser navigated to https://my.gov.az/. At least one featured service card is visible.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Locate the featured services section.
4. Note the name of the first service card.
5. Click the first service card (using the card link or button).
6. Wait for navigation to complete.
7. Take a browser snapshot.
8. Verify the URL has changed to a service-specific URL (not the homepage).
9. Verify the service detail page displays the service name matching the clicked card.

**Expected Result**: Clicking a featured service card navigates to the service detail page. The service detail URL is meaningful (e.g., /az/services/[service-id]). The service detail page displays information relevant to the selected service. No 404 or error page is shown.

---

### TC-022: Footer Is Present and Contains Expected Links

**Description**: Verify that the homepage footer is rendered and contains expected legal/navigation links.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Scroll to the bottom of the page.
3. Take a browser snapshot.
4. Verify the footer section is visible using `getByRole('contentinfo')`.
5. Verify the footer contains links such as "Elaqe" (Contact), "Haqqinda" (About), privacy policy, or terms of use.
6. Verify a copyright notice is present.

**Expected Result**: The footer is visible at the bottom of the homepage. Footer contains at least 2 navigation links. A copyright notice is present. Footer links are not broken (do not lead to 404).

---

### TC-023: Page Is Responsive on Mobile Viewport

**Description**: Verify that the homepage renders correctly on a mobile viewport (375x667 - iPhone SE equivalent).

**Preconditions**: Browser configured with mobile viewport (375x667 pixels).

**Steps**:
1. Set the browser viewport to 375x667 pixels (mobile).
2. Navigate to https://my.gov.az/.
3. Take a browser snapshot.
4. Verify the main navigation is either collapsed into a hamburger menu or renders correctly for mobile.
5. Verify the featured services section is readable (cards not overflowing or clipped).
6. Verify no horizontal scrollbar appears on the page.
7. If a hamburger menu is present, click it using `getByRole('button', { name: /menu/i })` and verify the navigation menu opens.
8. Verify the "All Services" link is accessible on mobile (visible and clickable).

**Expected Result**: The homepage renders without horizontal overflow on a 375px width viewport. A hamburger/mobile menu is present if the full navigation does not fit. The hamburger menu opens to reveal navigation links. Featured service cards are readable and scrollable on mobile. The "All Services" link is accessible and clickable on mobile.

---

### TC-024: Accessibility - Page Has Proper Heading Structure

**Description**: Verify that the homepage and services catalog page have a proper heading hierarchy for accessibility compliance.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Using the accessibility tree or browser tools, verify there is exactly one H1 heading on the page.
4. Verify that H2 headings appear for major sections (e.g., "Featured Services", "Categories").
5. Verify no heading levels are skipped (e.g., H1 directly to H3 without H2).
6. Navigate to https://my.gov.az/az/services.
7. Repeat the heading structure check on the services catalog page.

**Expected Result**: The homepage has exactly one H1 element. Major sections are marked with H2 headings. No heading levels are skipped. The services catalog page also follows the same heading hierarchy rules.

---

### TC-025: Accessibility - Interactive Elements Have Accessible Labels

**Description**: Verify that interactive elements on the homepage have accessible labels for screen reader compatibility.

**Preconditions**: Browser navigated to https://my.gov.az/.

**Steps**:
1. Navigate to https://my.gov.az/.
2. Take a browser snapshot.
3. Locate all navigation links in the header and verify each has non-empty text content or an aria-label attribute.
4. Locate the language toggle buttons and verify each has a meaningful label (e.g., "AZ", "RU", "EN").
5. Locate service cards in the featured section and verify the clickable area has descriptive text (not just "Click here" or empty anchor).
6. Locate the "All Services" button/link and verify it has meaningful text.
7. Navigate to https://my.gov.az/az/services and repeat checks for category filter buttons.

**Expected Result**: All navigation links have non-empty, descriptive text content. Language toggle controls have identifiable labels. Service card links have descriptive accessible names. Category filter buttons have text labels matching the category name. No interactive elements have empty aria-label and empty text content simultaneously.

---

### TC-026: Direct URL Navigation to Services Page Works

**Description**: Verify that navigating directly to https://my.gov.az/az/services works correctly without going through the homepage.

**Preconditions**: Fresh browser session with cleared cache.

**Steps**:
1. Open a new browser window.
2. Navigate directly to https://my.gov.az/az/services (bypassing the homepage).
3. Wait for the page to load.
4. Take a browser snapshot.
5. Verify the services catalog page loads correctly with category filters and service listings.
6. Verify the URL is https://my.gov.az/az/services.
7. Verify no redirect to homepage or error page occurs.

**Expected Result**: Navigating directly to /az/services loads the services catalog page correctly. The page does not redirect to the homepage or show a 404. Category filters and service listings are visible. The header navigation (including the language toggle) is functional.

---

### TC-027: Invalid URL Shows 404 or Redirect

**Description**: Verify that navigating to a non-existent URL within the portal shows an appropriate 404 page or redirects gracefully.

**Preconditions**: Fresh browser session.

**Steps**:
1. Navigate to https://my.gov.az/az/nonexistent-page-xyz-12345.
2. Wait for the page to load.
3. Take a browser snapshot.
4. Verify the page either shows a 404 error page or redirects to the homepage.
5. Verify the 404 page (if shown) has a user-friendly message in the appropriate language.
6. Verify the 404 page contains a link back to the homepage or services.

**Expected Result**: Non-existent URLs return a 404 error page or graceful redirect. The 404 page has a friendly message (not a raw server error). A link to return to the homepage or services is available. The header/footer of the site are still rendered on the 404 page.

---

### TC-028: Services Page Category Filter - Multiple Category Selection Behavior

**Description**: Verify the behavior when the user selects multiple categories on the services catalog page.

**Preconditions**: Browser navigated to https://my.gov.az/az/services. At least 2 categories are visible.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Take a browser snapshot.
3. Click the first category filter item.
4. Wait for the list to update.
5. Take a browser snapshot of filtered results.
6. Click a second category filter item.
7. Wait for the list to update.
8. Take a browser snapshot.
9. Observe if the list shows services from both categories (multi-select) or only the second category (single-select).

**Expected Result**: The application behaves consistently - either multi-select or single-select, but not unpredictably mixing both. If multi-select: services from both selected categories are shown. If single-select: only services from the most recently selected category are shown. The selected/active state of category buttons correctly reflects the current filter state. No JavaScript errors occur during category selection changes.

---

### TC-029: Scroll Position After Back Navigation from Service Detail

**Description**: Verify that the user's page position is handled correctly after returning from a service detail page.

**Preconditions**: Browser navigated to https://my.gov.az/az/services.

**Steps**:
1. Navigate to https://my.gov.az/az/services.
2. Scroll down past several service cards so the page is not at the top.
3. Click on a service card to navigate to the service detail page.
4. Wait for the service detail page to load.
5. Click the browser back button (or use `browser_navigate_back`).
6. Wait for the services page to reload or restore state.
7. Take a browser snapshot.
8. Verify the scroll position and whether services are still properly rendered.

**Expected Result**: After returning from a service detail page via back navigation, the user's scroll position is either preserved at the position where they clicked (good UX) or reset to the top of the services page. In either case, the services list is visible and no blank/broken state is shown. Services are properly rendered after back navigation.

---

### TC-030: No Critical Console Errors on Homepage and Services Page Load

**Description**: Verify that the homepage and services catalog page load without any critical JavaScript errors in the browser console.

**Preconditions**: Fresh browser session with console monitoring enabled.

**Steps**:
1. Open a new browser window with console monitoring enabled.
2. Navigate to https://my.gov.az/.
3. Wait for the page to fully load (wait for network idle).
4. Check the browser console for errors using `browser_console_messages`.
5. Verify there are no errors of severity "error" (critical JS errors, failed critical resource loads).
6. Note any warnings for documentation but do not fail on warnings alone.
7. Navigate to https://my.gov.az/az/services.
8. Repeat the console check on the services page.

**Expected Result**: No critical JavaScript errors appear in the console on the homepage. No critical errors appear on the services catalog page. Errors that prevent page functionality (e.g., "Uncaught ReferenceError", "Cannot read properties of undefined" affecting UI rendering) are treated as test failures.

---

## Summary Table

| Test ID | Description | Priority | Type |
|---------|-------------|----------|------|
| TC-001 | Homepage loads within 5 seconds | High | Performance |
| TC-002 | Homepage hero/banner visible | High | Functional |
| TC-003 | Navigation menu with top-level links | High | Functional |
| TC-004 | Featured services count > 0 | High | Functional |
| TC-005 | "All Services" link visible on homepage | High | Functional |
| TC-006 | "All Services" click navigates to /az/services | High | Functional |
| TC-007 | Services catalog shows categories | High | Functional |
| TC-008 | Category filter updates services list | High | Functional |
| TC-009 | Services catalog count > 0 | High | Functional |
| TC-010 | Service card shows required info | Medium | Functional |
| TC-011 | Language toggle visible on homepage | High | Functional |
| TC-012 | Language switch AZ to RU | High | Functional |
| TC-013 | Language switch AZ to EN | Medium | Functional |
| TC-014 | Language persists homepage to services | High | Functional |
| TC-015 | Language toggle on services page stays on services | Medium | Functional |
| TC-016 | Search filter on services page | Medium | Functional |
| TC-017 | Empty state on no-results filter | Medium | Edge Case |
| TC-018 | No indefinite spinner on API error | Medium | Error Handling |
| TC-019 | Breadcrumb navigation on services page | Low | Functional |
| TC-020 | Back navigation from services to homepage | Medium | Functional |
| TC-021 | Featured service card to service detail | High | Functional |
| TC-022 | Footer present with links | Low | Functional |
| TC-023 | Responsive design on mobile viewport | Medium | Responsive |
| TC-024 | Proper heading structure (accessibility) | Medium | Accessibility |
| TC-025 | Interactive elements have accessible labels | Medium | Accessibility |
| TC-026 | Direct URL navigation to /az/services | Medium | Functional |
| TC-027 | Invalid URL shows 404 or redirect | Low | Error Handling |
| TC-028 | Multiple category selection behavior | Medium | Edge Case |
| TC-029 | Scroll position after back navigation | Low | UX |
| TC-030 | No critical console errors on page load | High | Quality |

---

## Notes and Assumptions

1. The portal operates in Azerbaijani (AZ) by default when no language is set; additional languages are Russian (RU) and English (EN).
2. The "All Services" button text is expected to be "Butun xidmetler" in Azerbaijani; testers should adapt selectors to the active language at runtime.
3. The services catalog URL is assumed to be https://my.gov.az/az/services with the "az" language prefix; this prefix changes with language switching to /ru/services or /en/services.
4. Category filters may use either buttons with active/selected CSS states or radio-style inputs.
5. TC-017 and TC-018 (edge cases) may require simulated API errors or data manipulation; coordinate with the development team if these cannot be triggered in the live environment.
6. TC-023 (mobile responsive) should also be validated on actual mobile devices in addition to emulated viewports.
7. The featured services section on the homepage may be driven by a CMS or API; the count of services is expected to be > 0 in any valid production or staging environment.
8. No authentication is required to browse the homepage or services catalog; these are public-facing pages.
