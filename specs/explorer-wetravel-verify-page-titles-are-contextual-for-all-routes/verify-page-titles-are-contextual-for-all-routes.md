# Test Plan: Verify page titles are contextual for all routes

## Description
Verify that every authenticated route in the WeTravel dashboard sets a unique, contextual `<title>` that identifies the page context. Currently, all `/user/*` routes share the same generic title ("WeTravel - Itinerary, Booking and Payment solutions for Multi-Day Travel Businesses"), which is the marketing homepage tagline. Each page should instead display a title like "My Trips - WeTravel", "CRM - WeTravel", etc., based on the active section and page content.

## Evidence Summary
- **Baseline title (current bug)**: All 8 primary authenticated routes return `"WeTravel - Itinerary, Booking and Payment solutions for Multi-Day Travel Businesses"` (the marketing homepage tagline).
- **Public trip pages**: DO set contextual titles (e.g., `"Japan Trip in Baku, Azerbaijan"`), confirming the platform supports dynamic titles.
- **Sidebar navigation labels**: My Trips, Itineraries, CRM, Payments, Reports, Inventory, Network, Account.
- **h1 headings on pages**: "Upcoming Trips" (My Trips), "Opportunities" (CRM), "Overview" (Payments), "Payments Reporting" (Reports), "Resource list" (Inventory), no h1 (Network), "Itineraries" (Itineraries), "Profile" (Account).
- **Primary routes**: `/user/my_trips`, `/user/crm`, `/user/payments/balance`, `/user/reporting/payments`, `/user/inventory`, `/user/network`, `/user/itineraries`, `/user/account/profile`.
- **Sub-routes discovered**: My Trips sub-tabs (upcoming, past, draft, deactivated, archived, joined), CRM sub-routes (opportunities, contacts), Manage Trip (`/user/manage_trips/:id`), Itinerary Builder (`/itinerary_builder/:id`).
- **Leave-site dialogs**: Appear when navigating away from form pages (e.g., Itinerary Builder). Handle with `accept: true`.

---

### TC-001: My Trips page title is contextual

**Description:** Navigate to the My Trips page and verify the document title includes "My Trips" and is not the generic marketing tagline.

**Preconditions:**
- User is logged in to the WeTravel dashboard at https://pre.wetravel.to
- At least one trip exists in the account

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Wait for the page to fully load (heading "Upcoming Trips" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "My Trips" (e.g., "My Trips - WeTravel" or "Upcoming Trips - My Trips - WeTravel")
- The document title is NOT equal to "WeTravel - Itinerary, Booking and Payment solutions for Multi-Day Travel Businesses"
- The title uniquely identifies this page compared to other dashboard routes

**Test Data:**
- URL: `https://pre.wetravel.to/user/my_trips`
- Expected title pattern: contains "My Trips"

---

### TC-002: CRM page title is contextual

**Description:** Navigate to the CRM section and verify the document title includes "CRM" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/crm`
2. Wait for the page to fully load (heading "Opportunities" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "CRM" (e.g., "CRM - WeTravel" or "Opportunities - CRM - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from the My Trips page title

**Test Data:**
- URL: `https://pre.wetravel.to/user/crm` (redirects to `/user/crm/opportunities`)
- Expected title pattern: contains "CRM"

---

### TC-003: Payments page title is contextual

**Description:** Navigate to the Payments section and verify the document title includes "Payments" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/payments`
2. Wait for the redirect to `/user/payments/balance` and page to load (heading "Overview" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Payments" (e.g., "Payments - WeTravel" or "Balance - Payments - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/payments` (redirects to `/user/payments/balance`)
- Expected title pattern: contains "Payments"

---

### TC-004: Reports page title is contextual

**Description:** Navigate to the Reports section and verify the document title includes "Reports" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/reporting`
2. Wait for the redirect to `/user/reporting/payments` and page to load (heading "Payments Reporting" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Reports" (e.g., "Reports - WeTravel" or "Payments Reporting - Reports - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/reporting` (redirects to `/user/reporting/payments`)
- Expected title pattern: contains "Reports"

---

### TC-005: Inventory page title is contextual

**Description:** Navigate to the Inventory section and verify the document title includes "Inventory" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/inventory`
2. Wait for the page to load (heading "Resource list" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Inventory" (e.g., "Inventory - WeTravel" or "Resource list - Inventory - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/inventory`
- Expected title pattern: contains "Inventory"

---

### TC-006: Network page title is contextual

**Description:** Navigate to the Network section and verify the document title includes "Network" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/network`
2. Wait for the page to load
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Network" (e.g., "Network - WeTravel" or "WeTravel Network - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/network`
- Expected title pattern: contains "Network"

---

### TC-007: Itineraries page title is contextual

**Description:** Navigate to the Itineraries section and verify the document title includes "Itineraries" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/itineraries`
2. Wait for the page to load (heading "Itineraries" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Itineraries" (e.g., "Itineraries - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/itineraries`
- Expected title pattern: contains "Itineraries"

---

### TC-008: Account page title is contextual

**Description:** Navigate to the Account section and verify the document title includes "Account" context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/account/profile`
2. Wait for the page to load (heading "Profile" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Account" (e.g., "Account - WeTravel" or "Profile - Account - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is different from all other route titles

**Test Data:**
- URL: `https://pre.wetravel.to/user/account/profile`
- Expected title pattern: contains "Account"

---

### TC-009: All authenticated route titles are unique

**Description:** Navigate through all 8 primary authenticated routes sequentially and verify each returns a unique document title (no two routes share the same title).

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips` and capture the title
2. Navigate to `https://pre.wetravel.to/user/crm` and capture the title
3. Navigate to `https://pre.wetravel.to/user/payments` and capture the title
4. Navigate to `https://pre.wetravel.to/user/reporting` and capture the title
5. Navigate to `https://pre.wetravel.to/user/inventory` and capture the title
6. Navigate to `https://pre.wetravel.to/user/network` and capture the title
7. Navigate to `https://pre.wetravel.to/user/itineraries` and capture the title
8. Navigate to `https://pre.wetravel.to/user/account/profile` and capture the title
9. Collect all 8 titles into a set and verify uniqueness

**Expected Result:**
- All 8 titles are unique (no duplicates in the set)
- Each title contains a route-identifying keyword (My Trips, CRM, Payments, Reports, Inventory, Network, Itineraries, Account)
- No title equals the generic marketing tagline "WeTravel - Itinerary, Booking and Payment solutions for Multi-Day Travel Businesses"
- All titles contain "WeTravel" for brand consistency

**Test Data:**
- Routes: `/user/my_trips`, `/user/crm`, `/user/payments`, `/user/reporting`, `/user/inventory`, `/user/network`, `/user/itineraries`, `/user/account/profile`

---

### TC-010: Sub-route titles reflect deeper context (My Trips tabs)

**Description:** Navigate to the My Trips sub-tabs (Upcoming, Past, Draft, Deactivated, Archived, Joined) and verify each sub-route has a contextual title that distinguishes it from the parent My Trips page and from each other.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips/upcoming_trips` and capture the title
2. Navigate to `https://pre.wetravel.to/user/my_trips/past_trips` and capture the title
3. Navigate to `https://pre.wetravel.to/user/my_trips/draft_trips` and capture the title
4. Navigate to `https://pre.wetravel.to/user/my_trips/deactivated_trips` and capture the title
5. Navigate to `https://pre.wetravel.to/user/my_trips/archived_trips` and capture the title
6. Navigate to `https://pre.wetravel.to/user/my_trips/joined_trips` and capture the title
7. Verify all 6 titles are unique and contextual

**Expected Result:**
- Each sub-route title contains context about which tab is active (e.g., "Upcoming Trips - My Trips - WeTravel", "Past Trips - My Trips - WeTravel")
- All 6 titles are unique from each other
- All 6 titles contain "My Trips" or the tab name for context
- No title equals the generic marketing tagline

**Test Data:**
- Sub-routes: `/user/my_trips/upcoming_trips`, `/user/my_trips/past_trips`, `/user/my_trips/draft_trips`, `/user/my_trips/deactivated_trips`, `/user/my_trips/archived_trips`, `/user/my_trips/joined_trips`

---

### TC-011: Manage Trip page title includes trip name

**Description:** Navigate to the Manage Trip detail page for a specific trip and verify the title includes the trip name for easy browser tab identification.

**Preconditions:**
- User is logged in to the WeTravel dashboard
- At least one trip exists (e.g., "Japan Trip" with ID 9934590868)

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/manage_trips/9934590868`
2. Wait for the page to load (heading "Manage Trip" visible)
3. Read the document title via `page.title()`

**Expected Result:**
- The document title includes the trip name "Japan Trip" (e.g., "Japan Trip - Manage Trip - WeTravel" or "Manage Trip - Japan Trip - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title is unique compared to the main My Trips listing page title

**Test Data:**
- URL: `https://pre.wetravel.to/user/manage_trips/9934590868`
- Trip name: "Japan Trip"

---

### TC-012: Title updates on browser back/forward navigation

**Description:** Navigate between multiple dashboard sections using browser back/forward buttons and verify the page title updates to match the currently displayed route.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips` and capture title T1
2. Navigate to `https://pre.wetravel.to/user/crm` and capture title T2
3. Navigate to `https://pre.wetravel.to/user/payments` and capture title T3
4. Press browser Back button (should return to CRM page)
5. Read the document title and verify it matches T2
6. Press browser Back button again (should return to My Trips page)
7. Read the document title and verify it matches T1
8. Press browser Forward button (should go to CRM page)
9. Read the document title and verify it matches T2

**Expected Result:**
- After each back/forward navigation, the document title matches the title previously captured for that route
- Title updates correctly after navigation (not stale from previous page)
- T1, T2, and T3 are all different from each other
- No step shows the generic marketing tagline

**Test Data:**
- Route sequence: My Trips → CRM → Payments, then Back/Forward navigation

---

### TC-013: Public trip page title is contextual (positive baseline)

**Description:** Verify that public-facing trip pages already set contextual titles correctly, serving as a positive baseline. This confirms the platform's capability to set dynamic titles.

**Preconditions:**
- A published trip exists with URL slug

**Steps:**
1. Navigate to `https://pre.wetravel.to/trips/japan-trip-farhad-gambarov-9934590868`
2. Wait for the page to load
3. Read the document title via `page.title()`

**Expected Result:**
- The document title is contextual and includes the trip name (e.g., "Japan Trip in Baku, Azerbaijan")
- The document title is NOT the generic marketing tagline
- This confirms the platform CAN set dynamic titles, highlighting the gap on authenticated routes

**Test Data:**
- URL: `https://pre.wetravel.to/trips/japan-trip-farhad-gambarov-9934590868`
- Observed title: "Japan Trip in Baku, Azerbaijan"

---

### TC-014: CRM sub-routes have contextual titles

**Description:** Navigate between CRM sub-routes (Opportunities and Contacts) and verify each has a unique, contextual title.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/crm/opportunities` and capture the title
2. Navigate to `https://pre.wetravel.to/user/crm/contacts` and capture the title
3. Compare the two titles

**Expected Result:**
- The Opportunities page title contains "Opportunities" and "CRM" context (e.g., "Opportunities - CRM - WeTravel")
- The Contacts page title contains "Contacts" and "CRM" context (e.g., "Contacts - CRM - WeTravel")
- The two titles are different from each other
- Neither equals the generic marketing tagline

**Test Data:**
- URLs: `/user/crm/opportunities`, `/user/crm/contacts`

---

### TC-015: Itinerary Builder page title is contextual

**Description:** Navigate to the Itinerary Builder for a trip and verify the title includes context about the trip being edited.

**Preconditions:**
- User is logged in to the WeTravel dashboard
- A trip exists with an itinerary (e.g., "Japan Trip" with ID 9934590868)

**Steps:**
1. Navigate to `https://pre.wetravel.to/itinerary_builder/9934590868#/builder/trip-basics`
2. Wait for the page to load
3. Read the document title via `page.title()`

**Expected Result:**
- The document title contains "Itinerary Builder" or the trip name context (e.g., "Itinerary Builder - Japan Trip - WeTravel")
- The document title is NOT equal to the generic marketing tagline
- The title distinguishes this page from the Itineraries listing page

**Test Data:**
- URL: `https://pre.wetravel.to/itinerary_builder/9934590868#/builder/trip-basics`

---

### TC-016: Page title is correct after sidebar navigation

**Description:** Click through each sidebar navigation link and verify the page title updates to match the destination section, confirming the title is set by the client-side router (not just on full page loads).

**Preconditions:**
- User is logged in to the WeTravel dashboard
- User is on any dashboard page with the sidebar navigation visible

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Open the sidebar/hamburger menu by clicking the hamburger button
3. Click the "CRM" link in the sidebar navigation
4. Wait for the CRM page to load
5. Capture the document title
6. Click the "Payments" link in the sidebar navigation
7. Wait for the Payments page to load
8. Capture the document title
9. Click the "Reports" link in the sidebar navigation
10. Wait for the Reports page to load
11. Capture the document title
12. Click the "Inventory" link in the sidebar navigation
13. Wait for the Inventory page to load
14. Capture the document title
15. Click the "Network" link in the sidebar navigation
16. Wait for the Network page to load
17. Capture the document title
18. Click the "Itineraries" link in the sidebar navigation
19. Wait for the Itineraries page to load
20. Capture the document title
21. Click the "Account" link in the sidebar navigation
22. Wait for the Account page to load
23. Capture the document title

**Expected Result:**
- Each sidebar navigation click results in a page title that matches the destination section
- Titles transition correctly through each navigation (no stale titles from previous pages)
- All captured titles are unique
- The sidebar link selectors used: `getByRole('link', { name: 'CRM' })`, `getByRole('link', { name: 'Payments' })`, `getByRole('link', { name: 'Reports' })`, `getByRole('link', { name: 'Inventory' })`, `getByRole('link', { name: 'Network' })`, `getByRole('link', { name: 'Itineraries' })`, `getByRole('link', { name: 'Account' })`

**Test Data:**
- Starting URL: `https://pre.wetravel.to/user/my_trips`
- Sidebar selectors discovered: `link "My Trips"` [href=/user/my_trips], `link "CRM"` [href=/user/crm], `link "Payments"` [href=/user/payments/balance], `link "Reports"` [href=/user/reporting], `link "Inventory"` [href=/user/inventory], `link "Network"` [href=/user/network], `link "Itineraries"` [href=/user/itineraries], `link "Account"` [href=/user/account/profile]

---

### TC-017: Browser tab title is useful for multi-tab identification

**Description:** Open multiple dashboard routes in separate browser tabs and verify each tab's title is descriptive enough to distinguish them in the browser tab bar (short enough to be readable, unique enough to be identifiable).

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Open `https://pre.wetravel.to/user/my_trips` in Tab 1 and capture title
2. Open `https://pre.wetravel.to/user/crm` in Tab 2 and capture title
3. Open `https://pre.wetravel.to/user/payments` in Tab 3 and capture title
4. Open `https://pre.wetravel.to/user/reporting` in Tab 4 and capture title
5. Open `https://pre.wetravel.to/user/inventory` in Tab 5 and capture title
6. Open `https://pre.wetravel.to/user/network` in Tab 6 and capture title
7. Open `https://pre.wetravel.to/user/itineraries` in Tab 7 and capture title
8. Open `https://pre.wetravel.to/user/account/profile` in Tab 8 and capture title
9. Verify each title starts with a unique section name (not "WeTravel" prefix which would make tabs indistinguishable)
10. Verify the first 15-20 characters of each title are unique across tabs

**Expected Result:**
- Each tab's title starts with the section name (e.g., "My Trips - ...", "CRM - ...") not the brand name
- The first ~20 characters of each title uniquely identify the section
- A user can distinguish tabs in the browser tab bar without clicking into them
- All titles follow a consistent format (e.g., "Section Name - WeTravel")

**Test Data:**
- All 8 primary dashboard routes opened in separate tabs

---

### TC-018: Account sub-route titles are contextual

**Description:** Navigate between Account sub-routes (Profile, Settings) and verify each has a unique, contextual title.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/account/profile` and capture the title
2. Navigate to `https://pre.wetravel.to/user/account/settings` and capture the title
3. Compare the two titles

**Expected Result:**
- The Profile page title contains "Profile" and "Account" context (e.g., "Profile - Account - WeTravel")
- The Settings page title contains "Settings" and "Account" context (e.g., "Settings - Account - WeTravel")
- The two titles are different from each other
- Neither equals the generic marketing tagline

**Test Data:**
- URLs: `/user/account/profile`, `/user/account/settings`

---

### TC-019: No console errors when title is set on each route

**Description:** Navigate through all primary dashboard routes and verify no JavaScript errors are thrown during page load and title rendering. This is a regression check to ensure title-setting logic doesn't introduce errors.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Check browser console for errors
3. Navigate to `https://pre.wetravel.to/user/crm`
4. Check browser console for errors
5. Navigate to `https://pre.wetravel.to/user/payments`
6. Check browser console for errors
7. Navigate to `https://pre.wetravel.to/user/reporting`
8. Check browser console for errors
9. Navigate to `https://pre.wetravel.to/user/inventory`
10. Check browser console for errors
11. Navigate to `https://pre.wetravel.to/user/network`
12. Check browser console for errors
13. Navigate to `https://pre.wetravel.to/user/itineraries`
14. Check browser console for errors
15. Navigate to `https://pre.wetravel.to/user/account/profile`
16. Check browser console for errors

**Expected Result:**
- No uncaught JavaScript errors related to title setting on any route
- Each page loads without fatal console errors that could prevent title rendering
- Any existing console errors are pre-existing and unrelated to title logic

**Test Data:**
- All 8 primary dashboard routes

---

### TC-020: Page title is set correctly on mobile viewport

**Description:** Resize the browser to a mobile viewport and verify that page titles are still contextual and correct on each route, since mobile browsers rely heavily on titles for navigation context.

**Preconditions:**
- User is logged in to the WeTravel dashboard

**Steps:**
1. Set browser viewport to 375x812 (iPhone X size)
2. Navigate to `https://pre.wetravel.to/user/my_trips` and capture the title
3. Navigate to `https://pre.wetravel.to/user/crm` and capture the title
4. Navigate to `https://pre.wetravel.to/user/payments` and capture the title
5. Navigate to `https://pre.wetravel.to/user/itineraries` and capture the title
6. Reset viewport to default desktop size (1280x720)

**Expected Result:**
- All captured titles match the expected contextual titles (same as desktop)
- Titles do not degrade to the generic marketing tagline on mobile viewport
- The responsive layout does not affect the document title

**Test Data:**
- Mobile viewport: 375x812
- Routes tested: My Trips, CRM, Payments, Itineraries
