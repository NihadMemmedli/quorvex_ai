# Test Plan: Trip Publishing & Customer Trip Page

## Overview

**Application**: WeTravel - Trip Management Platform
**Target URL**: Generalized (selectors to be updated during code generation)
**Feature Under Test**: Trip Publishing & Customer Trip Page
**Date**: 2026-05-30

## Scope

This test plan covers the end-to-end workflows for admin trip creation with packages, resource inventory management for accommodations, connecting resources to packages, publishing a customer-facing trip page, customer package selection and booking, availability management via the resource calendar, and rooming list export. It includes happy path journeys, multi-step navigation flows, negative/error scenarios, edge cases with shared rooms and multiple resources, accessibility checks, and responsive rendering validation.

---

### TC-001: Admin Creates and Publishes a Simple Trip with Two Packages

**Description**: Verify that an admin user can create a new trip via the guided trip builder, add double and single occupancy packages, publish the trip, and see the resulting customer-facing trip page with both packages displayed.

**Preconditions**: Admin user is logged in with valid credentials. No trip with the same name exists. Inventory section is accessible.

**Steps**:
1. Navigate to the WeTravel admin dashboard.
2. Click the "Create Trip" or "New Trip" button in the trip builder.
3. Enter the trip name (e.g., "Izmir Week Retreat") in the trip name field.
4. Fill in the trip location field with "Izmir, Turkey".
5. Set the trip start date to a future date.
6. Set the trip end date to 7 days after the start date.
7. Navigate to the packages/pricing section of the trip builder.
8. Click "Add Package" or equivalent button.
9. Create the first package named "Full week program - Double occupancy" with a price.
10. Click "Add Package" again.
11. Create the second package named "Full week program - Single occupancy" with a price.
12. Click the "Publish" or "Publish Trip" button.
13. Wait for the publish confirmation or success message.
14. Navigate to the customer-facing trip page URL (via the share link or trip page preview).
15. Verify the trip page is publicly accessible and displays the trip title.
16. Verify both packages are listed on the customer trip page with names and prices.

**Expected Result**: The trip is successfully created and published without errors. A customer-facing trip page is generated and accessible. The page displays the trip name "Izmir Week Retreat". Both packages ("Full week program - Double occupancy" and "Full week program - Single occupancy") are visible with their respective prices. Customers can select either package.

**Test Data**:
- Trip name: "Izmir Week Retreat"
- Location: "Izmir, Turkey"
- Package 1: "Full week program - Double occupancy", price: $1,200
- Package 2: "Full week program - Single occupancy", price: $900

---

### TC-002: Admin Creates an Accommodation Resource and Connects It to Packages

**Description**: Verify that an admin can create an accommodation resource with a specific quantity and capacity, then connect that resource to multiple packages in the trip builder, so that package availability switches to "Based on resources availability".

**Preconditions**: Admin user is logged in. A published or draft trip with at least 2 packages exists (from TC-001 or equivalent). The Inventory section is accessible.

**Steps**:
1. Navigate to the Inventory section from the admin dashboard or trip management area.
2. Click "Create New Resource".
3. Select the resource type "Accommodation" from the type dropdown.
4. Enter the resource name "Izmir - Double rooms" in the name field.
5. Enter quantity as "15" in the quantity field.
6. Enter capacity as "2" in the capacity field.
7. Select the privacy option "Private only" (resource cannot be shared between bookings).
8. Click "Save" or "Create Resource".
9. Verify the new resource appears in the resource list with correct name, quantity, and capacity.
10. Navigate back to the trip builder for the relevant trip.
11. Go to the pricing section.
12. For the "Full week program - Double occupancy" package, click "Yes" on the "Connect resource to package?" toggle.
13. Select the resource "Izmir - Double rooms" from the resource list dropdown.
14. Verify the availability label changes to "Based on resources availability".
15. Repeat for the "Full week program - Single occupancy" package: click "Yes" on "Connect resource to package?".
16. Select the same resource "Izmir - Double rooms".
17. Verify availability for the single occupancy package also shows "Based on resources availability".
18. Optionally, restrict the single occupancy package to 5 units using the availability restriction field.
19. Save the trip.

**Expected Result**: The resource "Izmir - Double rooms" is created successfully with quantity 15 and capacity 2, set as "Private only". The resource appears in the resource list. Both packages are connected to the resource. The availability label for both packages changes to "Based on resources availability". If restricted, the single occupancy package shows a max of 5 units.

**Test Data**:
- Resource name: "Izmir - Double rooms"
- Type: Accommodation
- Quantity: 15
- Capacity: 2
- Privacy: Private only

---

### TC-003: Customer Views Published Trip Page and Selects a Package

**Description**: Verify that a customer (unauthenticated visitor) can access a published trip page, view available packages with pricing, and select a package to begin the booking process.

**Preconditions**: A trip has been published with at least 2 packages. The trip page URL is accessible. No booking has been made yet (full availability).

**Steps**:
1. Navigate to the published trip page URL (e.g., from a share link or direct URL).
2. Wait for the page to fully load.
3. Verify the trip title/name is visible and correct.
4. Verify the trip location and dates are displayed.
5. Verify the packages section lists all published packages.
6. Verify each package card shows the package name, price, and a selectable action (e.g., "Book Now" or "Select" button).
7. Click the "Select" or "Book Now" button on the "Full week program - Double occupancy" package.
8. Verify the booking flow is initiated (booking form appears, or navigation to checkout occurs).
9. Verify the selected package is indicated as the active choice (highlighted, checked, or added to cart).

**Expected Result**: The published trip page loads successfully. The trip title, location, and date range are displayed. All packages are listed with names and prices. Clicking "Select" or "Book Now" on a package initiates the booking flow. The selected package is visually indicated. No JavaScript errors occur during the interaction.

**Test Data**:
- Trip URL: Published trip page URL
- Expected packages: "Full week program - Double occupancy", "Full week program - Single occupancy"

---

### TC-004: Availability Decrements After Booking and Reflects on Resource Calendar

**Description**: Verify that after a customer books a package connected to a resource, the availability of both the package and the underlying resource is automatically decremented, and the Resource Calendar reflects the updated remaining count.

**Preconditions**: Admin is logged in. A trip with resource-connected packages exists. At least one booking has been completed for a package (e.g., "Full week program - Double occupancy"). Resource has quantity 15 and is connected to both double and single occupancy packages.

**Steps**:
1. Navigate to the admin dashboard.
2. Navigate to the Inventory section or the trip management area.
3. Click on "Resource Calendar" or navigate to the resource calendar view.
4. Locate the resource "Izmir - Double rooms" on the calendar.
5. Verify the remaining availability count has decreased (e.g., from 15 to 14 after 1 double occupancy booking).
6. Navigate to the published customer trip page.
7. Verify the package availability indicator shows updated remaining spots.
8. If the single occupancy package was restricted to 5, verify its availability is also decremented if bookings have been made.

**Expected Result**: The Resource Calendar shows the correct remaining room count after bookings. Availability is automatically adjusted without manual intervention. The customer-facing trip page reflects the updated availability. Both packages sharing the same resource show consistent availability (total resource count minus all bookings across connected packages).

**Test Data**:
- Resource: "Izmir - Double rooms" (initial quantity: 15)
- After 1 double occupancy booking: expected remaining = 14
- After 1 single occupancy booking: expected remaining = 13

---

### TC-005: Admin Creates Multiple Room Types with Sharing Options for Complex Scenario

**Description**: Verify that an admin can create multiple accommodation resources with different room configurations including shared and private options, multiple sharing option capacities, and connect them to specific packages.

**Preconditions**: Admin user is logged in. A new trip draft exists for "Colombia Retreat". The Inventory section is accessible.

**Steps**:
1. Navigate to the Inventory section.
2. Click "Create New Resource".
3. Create "Nuqui - Double rooms": type Accommodation, quantity 5, capacity 2, privacy "Private only". Save.
4. Click "Create New Resource" again.
5. Create "Nuqui - Single rooms": type Accommodation, quantity 4, capacity 1, privacy "Private only". Save.
6. Click "Create New Resource" again.
7. Create "Nuqui - Triple room": type Accommodation, quantity 1, capacity 3, privacy "Shared and private". Add sharing option "Shared girls" with capacity 3. Add sharing option "Shared boys" with capacity 3. Save.
8. Click "Create New Resource" again.
9. Create "Nuqui - Double queen": type Accommodation, quantity 10, capacity 4, privacy "Shared and private". Add sharing option "Shared girls" with capacity 4. Add sharing option "Shared boys" with capacity 4. Add sharing option "Shared adults" with capacity 2. Save.
10. Verify all 4 resources appear in the resource list with correct configurations.
11. Navigate to the trip builder for the Colombia Retreat trip.
12. Create 5 packages: (a) Double occupancy, (b) Single occupancy, (c) Shared adults, (d) Shared girls, (e) Shared boys.
13. For package (c) "Shared adults": click "Yes" on "Connect resource to package?", select "Nuqui - Double queen" with "Shared adults" sharing option.
14. For package (d) "Shared girls": connect both "Nuqui - Triple room" with "Shared girls" option AND "Nuqui - Double queen" with "Shared girls" option.
15. For package (e) "Shared boys": connect both "Nuqui - Triple room" with "Shared boys" option AND "Nuqui - Double queen" with "Shared boys" option.
16. Save and publish the trip.
17. Navigate to the customer trip page.
18. Verify all 5 packages are displayed.

**Expected Result**: All 4 accommodation resources are created with correct quantities, capacities, and sharing options. The resource list shows all resources. Each package is connected to the correct resource(s) with the correct sharing configuration. The trip publishes successfully. The customer trip page displays all 5 packages. Availability for each package is set to "Based on resources availability".

**Test Data**:
- Resource 1: "Nuqui - Double rooms", qty 5, cap 2, Private only
- Resource 2: "Nuqui - Single rooms", qty 4, cap 1, Private only
- Resource 3: "Nuqui - Triple room", qty 1, cap 3, Shared and private, options: Shared girls (3), Shared boys (3)
- Resource 4: "Nuqui - Double queen", qty 10, cap 4, Shared and private, options: Shared girls (4), Shared boys (4), Shared adults (2)

---

### TC-006: Shared Room Allocation Prevents Cross-Configuration Double Booking

**Description**: Verify that when a room is allocated to one sharing configuration (e.g., "Shared girls"), it cannot be simultaneously allocated to a different sharing configuration (e.g., "Shared boys") on the same dates.

**Preconditions**: The Colombia Retreat trip from TC-005 is published with shared room resources. The "Nuqui - Triple room" resource has only 1 unit with "Shared girls" and "Shared boys" sharing options.

**Steps**:
1. As a customer, navigate to the published trip page.
2. Select the "Full week program for girls with shared room" package and complete a booking for 3 participants.
3. Wait for the booking to be confirmed.
4. As a second customer, navigate to the same published trip page.
5. Verify the "Full week program for girls with shared room" package availability has decreased (the triple room is now fully booked for "Shared girls").
6. Verify the "Full week program for boys with shared room" package is still available (the "Shared boys" slot on the triple room has NOT been consumed by the girls booking — a specific room can only be booked by 1 configuration at a time, but since the triple room has capacity for both "Shared girls" and "Shared boys", verify the expected behavior per PRD: once one config is allocated, only that config's bookings are assigned to that room).
7. As admin, navigate to the Resource Calendar.
8. Verify the "Nuqui - Triple room" shows the allocation for "Shared girls" and remaining availability per configuration.

**Expected Result**: The "Shared girls" booking allocates the triple room to the girls configuration. The "Shared girls" availability is reduced (now 0 remaining for the triple room). The "Shared boys" configuration on the same triple room is NOT available simultaneously — a specific room can only be booked by 1 configuration. The Resource Calendar correctly reflects the allocation and remaining availability per sharing option.

**Test Data**:
- Resource: "Nuqui - Triple room" (qty 1, cap 3)
- Sharing options: "Shared girls" (cap 3), "Shared boys" (cap 3)

---

### TC-007: Publishing a Trip Without Required Fields Shows Validation Errors

**Description**: Verify that attempting to publish a trip without completing required fields (trip name, dates, at least one package) displays appropriate validation error messages and prevents publishing.

**Preconditions**: Admin user is logged in. A new draft trip is started but not completed.

**Steps**:
1. Navigate to the trip builder and start a new trip.
2. Leave the trip name field empty.
3. Leave the date fields empty.
4. Do not add any packages.
5. Click the "Publish" button.
6. Verify the publish action is blocked/prevented.
7. Verify validation error messages appear near the required fields (e.g., "Trip name is required", "Dates are required", "At least one package is required").
8. Fill in the trip name only.
9. Click "Publish" again.
10. Verify the publish is still blocked with remaining validation errors.
11. Fill in all required fields and add at least one package.
12. Click "Publish" again.
13. Verify the trip publishes successfully.

**Expected Result**: Publishing is blocked when required fields are missing. Validation error messages are clear and specific, appearing near the relevant fields. After correcting all validation errors, the trip publishes successfully. No partial or incomplete trip is published.

**Test Data**:
- Trip name: (empty → then "Validation Test Trip")
- Dates: (empty → then valid future dates)
- Packages: (none → then 1 package added)

---

### TC-008: Admin Exports Rooming List with Participant Resource Assignments

**Description**: Verify that an admin can export a rooming list from the Manage Trip section that includes each participant's assigned resource and sharing option.

**Preconditions**: Admin user is logged in. A trip with resource-connected packages exists. At least 3 bookings have been completed with different package/resource configurations. The Manage Trip export feature is available.

**Steps**:
1. Navigate to the admin dashboard.
2. Go to the "Manage Trip" section for the relevant trip.
3. Verify the participant list shows at least 3 participants.
4. Verify each participant entry includes the assigned resource name (e.g., "Izmir - Double rooms").
5. Verify each participant entry includes the sharing option when applicable (e.g., "Shared girls", "Shared adults").
6. Click the "Export" button or "Rooming List" export option.
7. Select the export format (e.g., CSV or Excel).
8. Download the exported file.
9. Open the exported file and verify it contains columns for: participant name, package, assigned resource, sharing option.
10. Verify the data in the export matches the data shown in the Manage Trip participant tab.

**Expected Result**: The participant list displays resource assignments for each participant. The rooming list export downloads successfully. The exported file contains accurate participant data with resource and sharing option columns. Data in the export matches the on-screen participant information. No data is missing or corrupted in the export.

**Test Data**:
- Expected export columns: Participant Name, Package, Assigned Resource, Sharing Option
- Expected at least 3 participant entries with correct resource mappings

---

### TC-009: Trip Builder Page Accessibility - Keyboard Navigation and ARIA Labels

**Description**: Verify that the trip builder page supports keyboard navigation through all interactive elements and that form controls, buttons, and toggles have proper accessible labels.

**Preconditions**: Admin user is logged in. A new draft trip is in progress in the trip builder.

**Steps**:
1. Navigate to the trip builder page.
2. Press the Tab key repeatedly to cycle through all interactive elements.
3. Verify the tab order follows a logical sequence (trip name → location → dates → packages section → publish button).
4. Verify each focused element has a visible focus indicator.
5. Verify each form input has an associated visible label or aria-label.
6. Verify the "Connect resource to package?" toggle has an accessible name (not just "Yes" / "No" without context).
7. Verify the "Create New Resource" button has a meaningful accessible label.
8. Verify the resource list dropdown has an accessible label describing its purpose.
9. Verify the "Publish" button has a clear accessible name (not just an icon).
10. Verify heading hierarchy: exactly one H1 on the page, H2 for major sections.

**Expected Result**: All interactive elements are reachable via keyboard Tab navigation. Tab order is logical and follows the visual layout. Every form input, button, toggle, and dropdown has a non-empty accessible label. Focus indicators are visible on all interactive elements. Heading structure is correct (one H1, H2s for sections). No element is keyboard-trapped (user can Tab through and Shift+Tab back).

**Test Data**:
- N/A (accessibility inspection, no data entry required)

---

### TC-010: Customer Trip Page Responsive Rendering on Mobile Viewport

**Description**: Verify that the published customer-facing trip page renders correctly on a mobile viewport (375x667 pixels) with readable package cards, accessible booking buttons, and no horizontal overflow.

**Preconditions**: A trip has been published with at least 2 packages. The trip page URL is accessible.

**Steps**:
1. Set the browser viewport to 375x667 pixels (iPhone SE equivalent).
2. Navigate to the published customer trip page URL.
3. Wait for the page to fully load.
4. Take a screenshot of the full page.
5. Verify the trip title is visible and not truncated.
6. Verify the trip location and dates are readable.
7. Scroll down to the packages section.
8. Verify each package card is fully visible and not clipped or overflowing horizontally.
9. Verify package names and prices are readable at the mobile viewport size.
10. Verify the "Select" or "Book Now" buttons are visible and tappable (minimum 44x44px touch target).
11. Verify no horizontal scrollbar appears on the page.
12. Verify the page header/navigation (if any) collapses to a mobile-friendly layout.
13. Tap the "Select" button on the first package.
14. Verify the booking flow initiates correctly on mobile.

**Expected Result**: The customer trip page renders without horizontal overflow at 375px width. All trip information (title, location, dates) is readable. Package cards display fully with names, prices, and action buttons visible. Buttons meet minimum touch target size (44x44px). The booking flow works on mobile. No layout breakage, clipped content, or horizontal scrolling.

**Test Data**:
- Viewport: 375x667 pixels (mobile)
- Expected packages: At least 2 packages visible

---

### TC-011: Package Availability Shows "Sold Out" When Resource Is Fully Consumed

**Description**: Verify that when all units of a connected resource are booked, the associated package displays a "Sold Out" or unavailable state on the customer trip page and no further bookings are accepted.

**Preconditions**: A trip with resource-connected packages exists. The resource "Izmir - Double rooms" has quantity 15 connected to both double and single occupancy packages. The single occupancy package is restricted to 5 units. Enough bookings exist to consume all availability.

**Steps**:
1. As admin, verify the resource "Izmir - Double rooms" shows 0 remaining availability in the Resource Calendar (all 15 rooms booked across both packages).
2. Navigate to the published customer trip page.
3. Verify the package "Full week program - Double occupancy" shows a "Sold Out", "Fully Booked", or unavailable indicator.
4. Verify the "Select" or "Book Now" button for the sold-out package is disabled, hidden, or shows a "Sold Out" label.
5. Attempt to click the "Select" button on the sold-out package.
6. Verify the booking is NOT initiated (no booking form appears).
7. Verify any other still-available packages on the same trip page remain bookable.

**Expected Result**: When all resource units are consumed, the connected package(s) show "Sold Out" or equivalent. The booking button is disabled or replaced with a "Sold Out" label. Clicking the sold-out button does not initiate a booking. Other packages with remaining availability remain fully bookable. No overbooking is possible.

**Test Data**:
- Resource: "Izmir - Double rooms" (qty 15, fully consumed)
- Expected: All connected packages show "Sold Out"

---

### TC-012: No Critical Console Errors on Trip Page and Builder Load

**Description**: Verify that the admin trip builder page and the customer-facing trip page load without any critical JavaScript errors in the browser console.

**Preconditions**: Admin user is logged in. A trip has been published. Fresh browser session with console monitoring enabled.

**Steps**:
1. Open a new browser window with console monitoring enabled.
2. Navigate to the admin trip builder page.
3. Wait for the page to fully load (wait for network idle).
4. Check the browser console for errors.
5. Verify there are no critical errors of severity "error" (no "Uncaught ReferenceError", "Cannot read properties of undefined", or failed critical resource loads).
6. Note any warnings but do not fail on warnings alone.
7. Navigate to the published customer trip page URL.
8. Wait for the page to fully load.
9. Check the browser console for errors again.
10. Verify no critical errors appear on the customer trip page.
11. Interact with a package (click "Select") on the customer page.
12. Check the console again for any errors triggered by the interaction.

**Expected Result**: No critical JavaScript errors appear in the console on either the trip builder or customer trip page. No errors are triggered by clicking a package selection button. Any warnings are non-critical (e.g., deprecation notices) and do not affect functionality.

**Test Data**:
- N/A (console error inspection)

---

## Summary Table

| Test ID | Description | Priority | Type |
|---------|-------------|----------|------|
| TC-001 | Admin creates and publishes trip with two packages | High | Happy Path |
| TC-002 | Admin creates accommodation resource and connects to packages | High | Happy Path |
| TC-003 | Customer views published trip page and selects a package | High | Happy Path |
| TC-004 | Availability decrements after booking, reflects on Resource Calendar | High | Navigation/State Transition |
| TC-005 | Admin creates multiple room types with sharing options | High | Happy Path (Complex Scenario) |
| TC-006 | Shared room allocation prevents cross-configuration double booking | High | Edge Case |
| TC-007 | Publishing without required fields shows validation errors | Medium | Negative/Error |
| TC-008 | Admin exports rooming list with participant resource assignments | Medium | Happy Path |
| TC-009 | Trip builder accessibility - keyboard navigation and ARIA labels | Medium | Accessibility |
| TC-010 | Customer trip page responsive rendering on mobile viewport | Medium | Responsive |
| TC-011 | Package shows "Sold Out" when resource is fully consumed | High | Negative/Error |
| TC-012 | No critical console errors on trip page and builder load | Medium | Quality/Regression |

---

## Notes and Assumptions

1. **No target URL provided**: All steps use generalized selectors. Actual selectors (accessibility IDs, resource-ids, CSS classes, XPath) must be discovered during code generation via browser exploration.
2. **Admin authentication**: Admin scenarios assume the user is already logged in with valid admin credentials. Credentials should be stored in environment variables (e.g., `WETRAVEL_ADMIN_EMAIL`, `WETRAVEL_ADMIN_PASSWORD`) and referenced via `{{WETRAVEL_ADMIN_EMAIL}}` placeholders.
3. **Resource availability calculation**: Per the PRD, when multiple packages are connected to the same resource, availability is automatically managed across all connected packages. Bookings from any connected package decrement the shared resource pool.
4. **Shared room exclusivity**: Per the PRD, "A specific room can only be booked by 1 configuration." Once a room is allocated to a sharing option (e.g., "Shared girls"), only bookings from packages with that same sharing option will be assigned to that room.
5. **Sharing options**: "Shared and private" resources allow both private bookings and shared configurations with named sharing groups (e.g., "Shared girls", "Shared boys", "Shared adults") each with their own capacity.
6. **Multi-resource packages**: Per the PRD, a single package can be connected to multiple resources (e.g., the "Shared girls" package connects to both "Nuqui - Triple room" and "Nuqui - Double queen").
7. **Customer trip page**: This is the public-facing page generated after publishing. It presents all packages with pricing and availability, allowing customers to select and book.
8. **Rooming list export**: The export is accessed from the Manage Trip section, participant tab, and includes resource assignments and sharing options per participant.
9. **Capacity vs. sharing**: Capacity refers to the number of people a room can hold. A "Private only" resource means the entire room is for one booking. "Shared and private" allows the room to be split into named sharing configurations.
10. **No adults/kids capacity split**: Per the PRD FAQ, the system does not support separate capacity for adults and kids.