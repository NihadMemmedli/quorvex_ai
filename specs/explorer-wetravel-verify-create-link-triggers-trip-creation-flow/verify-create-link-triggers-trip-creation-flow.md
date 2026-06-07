# Test Plan: Verify 'Create' link triggers trip creation flow

## Overview

This test plan covers the "Create" link navigation flow on WeTravel's pre-production environment
(https://pre.wetravel.to). The "Create" link, accessible from the hamburger navigation menu on the
My Trips page, routes to a creation hub page (`/itinerary_builder/create`) offering three distinct
creation paths: Full Trip, Payment Link, and Business Payment Request. Each path opens a dedicated
builder with form fields, auto-save, and publishing capabilities.

## Observed Selectors

| Element | Selector | Notes |
|---------|----------|-------|
| Hamburger Menu button | `getByRole('button', { name: 'Hamburger Menu' })` | Opens side navigation |
| Create link (in nav) | `getByRole('link', { name: 'Create' })` | href="#", triggers JS navigation to `/itinerary_builder/create` |
| My Trips link | `getByRole('link', { name: 'My Trips' })` | href="/user/my_trips" |
| Create Trip button | `getByRole('link', { name: 'Create Trip' })` | href="/itinerary_builder/new?skipPaymentLinkValidation=yes" |
| Create Payment Link button | `getByRole('link', { name: 'Create Payment Link' })` | href="/payment_link" |
| Create Request button | `getByRole('link', { name: 'Create Request' })` | href="/payment_request" |
| Sign Out button | `getByRole('button', { name: 'Sign Out' })` | In navigation |
| WeTravel Logo link | `getByRole('link', { name: 'WeTravel Logo' })` | Navigates to homepage |
| Trip Title field | `getByPlaceholder('e.g. Epic Japan Trip!')` | In itinerary builder |
| Destination field | `getByPlaceholder("What's the destination?")` | In itinerary builder |
| Search field | `getByPlaceholder('Search for participants and trips')` | On My Trips page |
| Trip Basics sidebar | `getByRole('link', { name: 'Trip Basics' })` | In builder sidebar |
| Trip Page sidebar | `getByRole('link', { name: 'Trip Page' })` | In builder sidebar |
| Packages sidebar | `getByRole('link', { name: 'Packages' })` | In builder sidebar |
| Add-ons sidebar | `getByRole('link', { name: 'Add-ons' })` | In builder sidebar |
| Participant Info sidebar | `getByRole('link', { name: 'Participant Info' })` | In builder sidebar |
| eSignature sidebar | `getByRole('link', { name: 'eSignature' })` | In builder sidebar |
| Settings sidebar | `getByRole('link', { name: 'Settings' })` | In builder sidebar |
| Preview button | `getByText('Preview')` | In builder sidebar |
| Publish button | `getByText('Publish')` | In builder sidebar |
| Next button | `getByText('Next')` | In builder footer |
| Start verification button | `getByRole('button', { name: 'Start your verification' })` | Account verification alert |
| Upload Document button | `getByRole('button', { name: 'Upload Document' })` | Payment Request builder |
| Create Request submit | `getByRole('button', { name: 'Create Request' })` | Payment Request builder submit |
| Sort combobox | `getByRole('combobox')` (on My Trips) | Sort options for trip list |
| List/Calendar toggle | Clickable generic with text "List" / "Calendar" | View toggle on My Trips |

## Observed URLs

| Page | URL |
|------|-----|
| My Trips | `https://pre.wetravel.to/user/my_trips?view=List` |
| Create Hub | `https://pre.wetravel.to/itinerary_builder/create` |
| Itinerary Builder (new) | `https://pre.wetravel.to/itinerary_builder/new?skipPaymentLinkValidation=yes` |
| Itinerary Builder (trip basics) | `https://pre.wetravel.to/itinerary_builder/{id}#/builder/trip-basics` |
| Payment Link Builder | `https://pre.wetravel.to/payment_link/{id}/builder` |
| Payment Request Builder | `https://pre.wetravel.to/payment_request/{id}/builder` |

## Observed API Endpoints

| Method | Endpoint | Status | Purpose |
|--------|----------|--------|---------|
| POST | `/v1/auth/tokens/access` | 201 | Access token refresh |
| POST | `/v1/draft_trips` | 201 | Create draft trip |
| GET | `/v1/payment_settings/{id}?product_type=b2b_payment_request` | 200 | Fetch payment settings |
| GET | `/v1/websites/status` | 200 | Website status check |

---

### TC-001: Navigate to Create hub from My Trips via hamburger menu Create link

**Description:** Verify that clicking the "Create" link in the hamburger navigation menu on the My Trips page navigates the user to the trip creation hub page.

**Preconditions:**
- User is logged in to WeTravel at https://pre.wetravel.to
- User is on the My Trips page (`/user/my_trips`)

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Click the hamburger menu button: `getByRole('button', { name: 'Hamburger Menu' })`
3. Verify the navigation menu opens and the "Create" link is visible
4. Click the "Create" link: `getByRole('link', { name: 'Create' })`

**Expected Result:**
- The page navigates to `https://pre.wetravel.to/itinerary_builder/create`
- The creation hub page is displayed with two sections: "Sell to Travelers" and "Collect from Business Partners"
- Three creation option cards are visible: "Full Trip", "Payment Link", and "Business Payment Request"
- Each card has a corresponding action link: "Create Trip", "Create Payment Link", "Create Request"
- No blocking JavaScript errors in the console (Sentry 429 errors are acceptable)

**Test Data:**
- Target URL: `https://pre.wetravel.to/user/my_trips`
- Expected destination: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-002: Create hub page renders all three creation options

**Description:** Verify that the creation hub page at `/itinerary_builder/create` displays all three creation paths with correct labels, descriptions, and action buttons.

**Preconditions:**
- User is logged in
- User navigates to `https://pre.wetravel.to/itinerary_builder/create`

**Steps:**
1. Navigate to `https://pre.wetravel.to/itinerary_builder/create`
2. Verify the page heading "Sell to Travelers" is visible
3. Verify the "Full Trip" card displays with description "Build a complete trip to share with participants"
4. Verify the "Create Trip" link is present: `getByRole('link', { name: 'Create Trip' })`
5. Verify the "Payment Link" card displays with description "Quickly create a payment link to collect a one-time payment"
6. Verify the "Create Payment Link" link is present: `getByRole('link', { name: 'Create Payment Link' })`
7. Verify the heading "Collect from Business Partners" is visible
8. Verify the "Business Payment Request" card displays with description "Create a request and attach an invoice to get paid by partners"
9. Verify the "Create Request" link is present: `getByRole('link', { name: 'Create Request' })`

**Expected Result:**
- All three creation option cards are rendered
- Each card contains an image/icon, title, description, and action link
- The "Sell to Travelers" section contains Full Trip and Payment Link
- The "Collect from Business Partners" section contains Business Payment Request
- All action links are clickable and have valid href attributes

**Test Data:**
- Target URL: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-003: Create Trip opens the Itinerary Builder with Trip Basics form

**Description:** Verify that clicking "Create Trip" on the creation hub page opens the Itinerary Builder with the Trip Basics form pre-loaded.

**Preconditions:**
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

**Steps:**
1. Click the "Create Trip" link: `getByRole('link', { name: 'Create Trip' })`
2. Verify the URL changes to `/itinerary_builder/{id}#/builder/trip-basics`
3. Verify the left sidebar is visible with navigation links: Trip Basics (active), Trip Page, Packages, Add-ons, Participant Info, eSignature, Settings
4. Verify the "Trip Title" textbox is present: `getByPlaceholder('e.g. Epic Japan Trip!')`
5. Verify the "Destination" textbox is present: `getByPlaceholder("What's the destination?")`
6. Verify the "Trip is Offered" dropdown is present with default value "One Time"
7. Verify Start Date and End Date fields are present
8. Verify the Group Size section with Min and Max fields
9. Verify the visibility options "Private" and "Public" are displayed
10. Verify the sidebar shows "Preview" and "Publish" options
11. Verify the "3 steps left before you can publish" message is visible
12. Verify the "Saved as draft" status is shown in the footer

**Expected Result:**
- The Itinerary Builder opens with the Trip Basics form
- All expected form fields are rendered and interactive
- The sidebar navigation highlights "Trip Basics" as active
- A draft trip is auto-created (API call to `POST /v1/draft_trips` returns 201)
- Auto-save status indicator is visible

**Test Data:**
- Starting URL: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-004: Create Payment Link opens the Payment Link Builder

**Description:** Verify that clicking "Create Payment Link" on the creation hub page opens the Payment Link builder form with all expected fields.

**Preconditions:**
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

**Steps:**
1. Click the "Create Payment Link" link: `getByRole('link', { name: 'Create Payment Link' })`
2. Verify the URL changes to `/payment_link/{id}/builder`
3. Verify the "Title" textbox is present with placeholder "Epic Japan Trip Payment Link"
4. Verify the "Trip ID" textbox is present with placeholder "ZXN-121"
5. Verify the "Trip Dates" field with start/end date is present
6. Verify the "Amount" textbox is present
7. Verify the currency dropdown is present with "USD" selected by default
8. Verify the "Add Deposit / Payment Plan" toggle (Yes/No) is present
9. Verify the "Add Expiration Date" toggle (Yes/No) is present
10. Verify the "Who pays the fees?" section with Organizer/Participant options
11. Verify the "Publish" button is present: `getByRole('button', { name: 'Publish' })`
12. Verify "Saved as draft" status text is visible

**Expected Result:**
- The Payment Link builder opens with all form fields
- Title, Trip ID, Dates, Amount, and Currency fields are rendered
- Deposit/Payment Plan and Expiration Date toggles are present
- Fee payer selection options are displayed
- Publish button is visible
- Auto-save status is shown

**Test Data:**
- Starting URL: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-005: Create Request opens the Business Payment Request Builder

**Description:** Verify that clicking "Create Request" on the creation hub page opens the Business Payment Request builder form with all expected fields.

**Preconditions:**
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

**Steps:**
1. Click the "Create Request" link: `getByRole('link', { name: 'Create Request' })`
2. Verify the URL changes to `/payment_request/{id}/builder`
3. Verify the "Title" textbox is present with placeholder "e.g. Epic Japan Trip Payment Request"
4. Verify the "Request ID" textbox is present with placeholder "e.g. ZXN-121"
5. Verify the "Due Date" field is present with calendar picker
6. Verify the "Amount" textbox is present
7. Verify the currency dropdown is present with "USD" selected
8. Verify the "Upload a document" section with "Upload Document" button
9. Verify the "Reference" textbox is present with placeholder "Write the purpose of your request here..."
10. Verify the "Who pays the fees?" section with Organizer/Payer options
11. Verify the "Link a trip (optional)" search field is present
12. Verify the "Create Request" submit button is present: `getByRole('button', { name: 'Create Request' })`

**Expected Result:**
- The Business Payment Request builder opens with all form fields
- Title, Request ID, Due Date, Amount, Currency fields are rendered
- Document upload section (PDF, up to 20MB) is present
- Reference text area is present
- Fee payer selection with Organizer/Payer options is displayed
- Trip linking search is available
- Create Request submit button is visible

**Test Data:**
- Starting URL: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-006: Itinerary Builder sidebar navigation between sections

**Description:** Verify that the Itinerary Builder sidebar allows navigation between all builder sections and updates the URL hash and active state correctly.

**Preconditions:**
- User is logged in
- A new trip is being created in the Itinerary Builder (user is on `#/builder/trip-basics`)

**Steps:**
1. From the Trip Basics view, click "Trip Page" in sidebar: `getByRole('link', { name: 'Trip Page' })`
2. Verify URL hash changes to `#/builder/trip-page`
3. Verify the "About this trip" rich text editor section is displayed
4. Verify the "What's Included?" and "What's not Included?" sections are visible
5. Click "Packages" in sidebar: `getByRole('link', { name: 'Packages' })`
6. Verify URL hash changes to `#/builder/packages`
7. Verify the package form with name, description, price, currency, and availability fields
8. Click "Trip Basics" in sidebar: `getByRole('link', { name: 'Trip Basics' })`
9. Verify URL hash changes back to `#/builder/trip-basics`
10. Verify the Trip Title and Destination fields are displayed again

**Expected Result:**
- Each sidebar link navigates to the correct builder section
- URL hash updates to match the section (trip-basics, trip-page, packages, etc.)
- Active state indicator moves to the currently selected section
- Content area updates to show the relevant form for each section
- No page reload occurs (SPA navigation)

**Test Data:**
- Starting URL: `https://pre.wetravel.to/itinerary_builder/create`
- Navigate to "Create Trip" first

---

### TC-007: Trip Basics form field interactions in Itinerary Builder

**Description:** Verify that the Trip Basics form fields in the Itinerary Builder accept input correctly and that form state is maintained.

**Preconditions:**
- User is logged in
- User is on the Itinerary Builder Trip Basics page

**Steps:**
1. Click the "Trip Title" textbox: `getByPlaceholder('e.g. Epic Japan Trip!')`
2. Type "Test Trip Automation"
3. Verify the character counter shows remaining characters (70 - length of input)
4. Click the "Destination" textbox: `getByPlaceholder("What's the destination?")`
5. Type "Tokyo, Japan"
6. Verify the "Trip is Offered" combobox shows "One Time" by default
7. Select "Recurring trip" from the combobox
8. Verify "Recurring trip" is now selected
9. Locate the Group Size Min field (default value "1") and Max field (default value "25")
10. Clear the Max field and type "50"
11. Verify the visibility section shows "Private" and "Public" options
12. Verify the "Enable waitlist when sold out?" toggle with Yes/No options

**Expected Result:**
- Trip Title field accepts text input and shows character count
- Destination field accepts text input
- Trip is Offered dropdown toggles between "One Time" and "Recurring trip"
- Group Size fields accept numeric input
- Visibility options are selectable (Private/Public)
- Waitlist toggle is interactive
- Auto-save triggers after field changes ("Saved as draft" timestamp updates)

**Test Data:**
- Trip Title: "Test Trip Automation"
- Destination: "Tokyo, Japan"
- Max Group Size: "50"

---

### TC-008: Navigation away from builder triggers unsaved changes dialog

**Description:** Verify that navigating away from an active trip builder form triggers a browser "Leave site?" dialog to prevent accidental data loss.

**Preconditions:**
- User is logged in
- User is on the Itinerary Builder (Trip Basics page) with a draft trip in progress

**Steps:**
1. Navigate to the Itinerary Builder Trip Basics page
2. Make a change to the form (e.g., enter a trip title)
3. Attempt to navigate away by going to `https://pre.wetravel.to/itinerary_builder/create`
4. Verify a "beforeunload" dialog appears
5. Accept the dialog (click "Leave")
6. Verify the browser navigates to the creation hub page

**Expected Result:**
- A "beforeunload" dialog is triggered when navigating away from an active builder
- Accepting the dialog allows navigation to proceed
- Declining the dialog (if tested) keeps the user on the builder page
- The dialog prevents accidental data loss

**Test Data:**
- Starting URL: Itinerary Builder page
- Target navigation URL: `https://pre.wetravel.to/itinerary_builder/create`

---

### TC-009: Create link accessible from different app pages via hamburger menu

**Description:** Verify that the "Create" link in the hamburger navigation menu is accessible and functional from multiple pages in the application, not just My Trips.

**Preconditions:**
- User is logged in

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Open hamburger menu, verify "Create" link is present, close menu
3. Navigate to `https://pre.wetravel.to/user/itineraries`
4. Open hamburger menu: `getByRole('button', { name: 'Hamburger Menu' })`
5. Verify the "Create" link is visible in the navigation
6. Click "Create": `getByRole('link', { name: 'Create' })`
7. Verify navigation to `/itinerary_builder/create`
8. Navigate to `https://pre.wetravel.to/user/payments/balance`
9. Open hamburger menu and verify "Create" link is present
10. Click "Create" and verify navigation to `/itinerary_builder/create`

**Expected Result:**
- The "Create" link is consistently available in the hamburger navigation from all app pages
- Clicking "Create" from any page navigates to `/itinerary_builder/create`
- The creation hub page loads correctly regardless of the referring page

**Test Data:**
- Test URLs: `/user/my_trips`, `/user/itineraries`, `/user/payments/balance`

---

### TC-010: My Trips page displays existing trips and view controls

**Description:** Verify that the My Trips page loads with existing trip cards, search, filter, sort, and view toggle controls that provide context for the Create flow.

**Preconditions:**
- User is logged in
- At least one trip exists in the user's account

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Verify the page title "My Trips" is visible in the header
3. Verify the search textbox is present: `getByPlaceholder('Search for participants and trips')`
4. Verify the "Filters" toggle is present
5. Verify the sort combobox is present with default "Date Created: Latest"
6. Verify all sort options exist: "Date Created: Earliest", "Departure Date: Earliest", "Departure Date: Latest", "Trip Name: A to Z", "Trip Name: Z to A"
7. Verify the "Upcoming Trips" heading is visible
8. Verify the List/Calendar view toggle is present
9. Verify at least one trip card is displayed (e.g., "Japan Trip")
10. Verify the trip card shows trip name, date, owner, amount, and participant count
11. Verify the trip card has action links: Itinerary Builder, Trip Page, Manage Trip

**Expected Result:**
- My Trips page loads with all UI controls
- Search, filters, and sort are functional
- Existing trip cards display trip metadata (name, date, owner, amount, participants)
- Trip card action links are present and clickable
- List/Calendar toggle is available

**Test Data:**
- Target URL: `https://pre.wetravel.to/user/my_trips`
- Expected existing trip: "Japan Trip" (or other user-owned trip)

---

### TC-011: Account verification warning banner on My Trips page

**Description:** Verify that when the user account is not verified, a warning banner is displayed on the My Trips page prompting the user to start verification.

**Preconditions:**
- User is logged in with an unverified account

**Steps:**
1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Verify a warning banner is visible with the message "Your account is not verified. Your trip pages will not be visible until verification is completed."
3. Verify the "Start your verification" button is present: `getByRole('button', { name: 'Start your verification' })`
4. Verify the warning icon is displayed alongside the message

**Expected Result:**
- A warning banner with a warning icon is displayed
- The warning text states that trip pages will not be visible until verification is completed
- A "Start your verification" call-to-action button is present
- The warning does not block the user from accessing the Create flow

**Test Data:**
- Target URL: `https://pre.wetravel.to/user/my_trips`
- Account state: Unverified

---

### TC-012: Create hub page responsive rendering and no blocking console errors

**Description:** Verify that the creation hub page renders correctly on desktop viewport without blocking JavaScript errors and with no application-level console errors.

**Preconditions:**
- User is logged in

**Steps:**
1. Navigate to `https://pre.wetravel.to/itinerary_builder/create`
2. Set viewport to 1920x1080 (desktop)
3. Verify all three creation option cards are visible without horizontal scrolling
4. Verify the navigation header with WeTravel Logo and hamburger menu is present
5. Verify the footer with Terms, Privacy Policy links is present
6. Check the browser console for errors
7. Verify no application-blocking errors exist (ignore third-party: Sentry 429, GTM aborts, Facebook pixel blocks)
8. Verify the page title is "WeTravel - Itinerary, Booking and Payment solutions for Multi-Day Travel Businesses"

**Expected Result:**
- Page renders fully at 1920x1080 viewport
- All content is visible without scrolling issues
- Navigation and footer are intact
- No application-originating console errors
- Page title is correct
- Third-party analytics errors (Sentry 429, GTM aborts) are expected and non-blocking

**Test Data:**
- Target URL: `https://pre.wetravel.to/itinerary_builder/create`
- Viewport: 1920x1080
