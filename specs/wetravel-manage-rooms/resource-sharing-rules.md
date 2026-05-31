# Test Plan: Resource Sharing Rules

**Target Application**: https://pre.wetravel.to/#
**Feature**: Resource Sharing Rules — defines whether a resource can be shared across participants, configures sharing options with per-option capacity constraints, enforces room allocation rules, and integrates with packages and rooming list exports.
**Evidence Sources**: Live browser exploration of WeTravel homepage, sign-in dialog, Help Center articles (Inventory Management How-To Guide, Resource List, Resource Calendar, Lists How-To Guide), mobile responsive testing (375x812), network request observation.

---

### TC-001: Authentication Gate for Resource Management

**Description:** Verify that the resource management features (Inventory, Resource List, Resource Calendar) are gated behind authentication and that the sign-in dialog functions correctly.

**Preconditions:**
- No active session (logged out)
- Browser at desktop viewport (1280x900)

**Steps:**
1. Navigate to `https://pre.wetravel.to/#`
2. Click the **"Sign In"** link in the top navigation (`getByRole('link', { name: 'Sign In' })`)
3. Observe the sign-in dialog opens
4. Verify the dialog heading reads **"Welcome"**
5. Verify the textbox labeled **"Your Email"** is present (`getByRole('textbox', { name: 'Your Email' })`)
6. Verify the **"Next"** button is visible (generic element with text "Next")
7. Verify social login buttons are present: **"Continue with Google"**, **"Continue with Facebook"**, **"Continue with LinkedIn"**
8. Close the dialog by clicking the close (X) icon (`img` inside `alert` within the dialog)
9. Navigate directly to an inventory URL (e.g., `https://pre.wetravel.to/#/inventory/resource-list`)
10. Verify the page redirects to login or shows an authentication-required state

**Expected Result:**
- Sign-in dialog opens successfully with all authentication options
- Dialog heading "Welcome" and subtitle "Enter your email to sign up or log in." are visible
- Email textbox, Next button, and three social login options are present and interactive
- Direct navigation to inventory routes is gated by authentication (redirects or shows auth prompt)
- No console errors on dialog open/close

**Test Data:** URL: `https://pre.wetravel.to/#`

---

### TC-002: Create Shared Resource with Sharing Options

**Description:** Verify that an organizer can create a new accommodation resource configured as "Shared" with multiple named sharing options, each with individual capacity constraints.

**Preconditions:**
- Authenticated as a trip organizer with Pro plan subscription
- An active or draft trip exists
- No existing resource named "Retreat - Double Queen Room"

**Steps:**
1. Log in as a trip organizer with Pro plan access
2. Navigate to the trip dashboard for an existing trip
3. Click **"Inventory"** in the left sidebar
4. Click **"Resource List"**
5. Click the **"Create New Resource"** button
6. Set the resource **name** to `"Retreat - Double Queen Room"`
7. Verify the **resource type** defaults to **"Accommodation"**
8. Set the **total quantity** to `10` rooms
9. Set the **capacity per room** to `4` people
10. Toggle the sharing setting from **"Private"** to **"Shared"**
11. Add a sharing option: name = `"Shared girls"`, capacity = `4`
12. Add a sharing option: name = `"Shared boys"`, capacity = `4`
13. Add a sharing option: name = `"Shared adults"`, capacity = `2`
14. Click **"Create"** or **"Save"** to save the resource
15. Verify the new resource appears in the Resource List with correct details

**Expected Result:**
- Resource creation form opens with name, type, quantity, capacity fields
- Sharing toggle can be switched from "Private" to "Shared"
- When shared, multiple sharing options can be added with individual names and capacities
- Each sharing option has a name field and a capacity field
- Resource is saved successfully and appears in the Resource List
- Resource list shows the resource name, quantity (10), capacity (4), and sharing options

**Test Data:** Resource: "Retreat - Double Queen Room", Quantity: 10, Capacity: 4, Sharing Options: "Shared girls" (4), "Shared boys" (4), "Shared adults" (2)

---

### TC-003: Allocation Enforcement — One Sharing Configuration Per Room

**Description:** Verify that a specific room is assigned to only one sharing configuration at a time, preventing incompatible bookings from sharing the same room.

**Preconditions:**
- Authenticated trip organizer
- A trip with shared resources configured (e.g., "Retreat - Double Queen Room" with "Shared girls" and "Shared boys" options)
- Existing bookings under "Shared girls" option that have allocated specific rooms
- At least one participant booked under "Shared boys" package

**Steps:**
1. Navigate to **Inventory > Resource Calendar**
2. Select a date range that has existing "Shared girls" bookings
3. Identify a room that has been assigned to a **"Shared girls"** configuration
4. Verify the room shows only participants from the "Shared girls" sharing option
5. Navigate to the booking management page
6. Attempt to add a "Shared boys" participant to the same room
7. Select a participant with a "Shared boys" package and try to assign them to the room already allocated to "Shared girls"
8. Verify the system prevents or warns about the incompatible sharing configuration
9. Return to the Resource Calendar for the same date
10. Confirm only one sharing option is active per room on the given date

**Expected Result:**
- Resource Calendar displays bookings grouped by sharing configuration per room
- A room assigned to "Shared girls" only shows participants from that sharing option
- System prevents or warns when attempting to assign an incompatible sharing configuration to an already-allocated room
- Each room on a given date is associated with exactly one sharing option
- No cross-configuration participant assignments are permitted

---

### TC-004: Connect Package to Resource with Sharing Option

**Description:** Verify that packages can be connected to resources with specific sharing options, and that package availability becomes resource-based after connection.

**Preconditions:**
- Authenticated trip organizer
- A trip with existing packages (e.g., "Full-week program for girls with shared room", "Full-week program for boys with shared room")
- At least one shared resource created with sharing options

**Steps:**
1. Open the **Trip Builder** for an existing trip
2. Scroll to the **Pricing section**
3. For a package, locate and click **"Yes"** on **"Connect resource to package?"**
4. Select **"Shared"** as the accommodation type
5. Choose the resource (e.g., "Retreat - Double Queen Room") from the dropdown
6. Select the **"Shared girls"** sharing option from the sharing option dropdown
7. Set the **package occupancy**
8. Click **"Connect"**
9. Verify the package availability changes to **"Based on resources availability"**
10. Repeat steps 3-8 for another package, selecting **"Shared boys"** sharing option
11. Verify both packages show as connected to the same resource with different sharing options

**Expected Result:**
- "Connect resource to package?" toggle is available for each package in the pricing section
- When toggled to "Yes", accommodation type selection (Private/Shared) appears
- Selecting "Shared" reveals the sharing option dropdown
- Sharing options matching the resource configuration are selectable
- After connecting, package availability switches to "Based on resources availability"
- Multiple packages can connect to the same resource with different sharing options
- System correctly tracks which sharing option each package uses

---

### TC-005: Resource List CRUD Operations

**Description:** Verify full CRUD operations on the Resource List: view details, edit, save, and delete resources with proper guard rails for connected resources.

**Preconditions:**
- Authenticated trip organizer with Pro plan
- At least one existing resource with active bookings (for delete-prevention test)
- At least one resource without connections (for delete-success test)

**Steps:**
1. Navigate to **Inventory > Resource List**
2. Verify the Resource List page loads showing all created resources
3. Click the **three-dot menu** (⋮) next to an existing resource
4. Click **"View Details"**
5. Verify the detail view shows: resource name, quantity, capacity, sharing options, and connected trips
6. Close the detail view
7. Click the **three-dot menu** again and select **"Edit resource"**
8. Change the resource name to `"Updated Room Name"`
9. Change the quantity from `10` to `15`
10. Click **"Save"**
11. Verify the resource name and quantity are updated in the list
12. Attempt to **delete** a resource that has active reservations or is connected to packages
13. Verify the system prevents deletion and shows an appropriate message
14. Create a new standalone resource without connections, then delete it
15. Verify the resource is successfully removed from the list

**Expected Result:**
- Resource List page loads and displays all created resources
- "View Details" shows complete resource information including connected trips and sharing options
- Edit form allows modifying resource name, quantity, capacity, and sharing options
- "Save" persists changes and the list view updates immediately
- Resources with active reservations or package connections cannot be deleted (blocked with message)
- Unconnected resources can be deleted successfully

---

### TC-006: Resource Calendar Availability and Overbooking Detection

**Description:** Verify the Resource Calendar shows date-based availability, detects overbookings, displays the "Overbooked" tag in red, and allows editing to resolve overbookings.

**Preconditions:**
- Authenticated trip organizer
- A trip with shared resources and existing bookings that exceed resource capacity for some dates
- Overbooking condition exists on at least one date

**Steps:**
1. Navigate to **Inventory > Resource Calendar**
2. Verify the calendar loads with dates showing resource availability indicators
3. Click on a **specific date** to view detailed resource information
4. Verify the detail panel shows: **Date**, **Availability count**, **Quantity**, and **Bookings list**
5. Identify dates where bookings exceed resource quantity
6. Verify a red **"Overbooked"** tag appears next to the resource name
7. Click the **"Overbooked"** tag
8. Verify a **30-day calendar** starting from the first overbooked date is displayed
9. Click the **"Edit Resource"** button in the upper right corner of the detail panel
10. Verify the edit form opens allowing adjustments to resource quantity

**Expected Result:**
- Resource Calendar loads with date-based availability view
- Clicking a date reveals a detailed resource information panel
- Availability count correctly reflects remaining capacity (total minus booked)
- Overbooked dates display a red "Overbooked" tag next to the resource name
- Clicking "Overbooked" tag shows a 30-day calendar from the first overbooking date
- "Edit Resource" button allows correcting overbooking by adjusting quantity
- Calendar updates after edits to reflect corrected availability

---

### TC-007: Rooming List Export with Sharing Option Details

**Description:** Verify that a rooming list can be created, participants assigned to rooms, columns customized to include resource and sharing option data, and the list exported with full details.

**Preconditions:**
- Authenticated trip organizer with Pro plan
- A trip with participants who have booked packages connected to shared resources
- At least 5 participants assigned to rooms

**Steps:**
1. Navigate to the **trip dashboard**
2. Click **"Lists"** in the left sidebar (accessed via Manage Trip dashboard)
3. Click **"Create List"** and select **"Rooming List"** (or room type)
4. If prompted (for recurring trips), select a departure date
5. Create rooms with: name, number of rooms, capacity, and package filter
6. Assign participants to rooms by clicking the **Room dropdown** for each participant
7. Verify participants are correctly grouped by room
8. Verify cancelled participants are **not included** in the participant list
9. Click **"Edit Columns"** and select columns for resource and sharing option information
10. Click **"Apply"** to update the table view
11. Click the **"Export"** button
12. Verify the exported file downloads and includes participant name, assigned resource, and sharing option details

**Expected Result:**
- Rooming list can be created from the Lists section
- Participants can be assigned to rooms via Room dropdown
- Only active (non-cancelled) participants appear in the list
- Custom columns (resource, sharing option) can be added via "Edit Columns"
- Export generates a downloadable file containing all visible columns
- Exported data includes participant assignment details and resource/sharing information

---

### TC-008: Edit or Add Resource for Specific Booking

**Description:** Verify that a trip organizer can edit or add resource assignments for specific participant bookings, including changing resources and sharing options, without triggering email notifications to customers.

**Preconditions:**
- Authenticated trip organizer
- A trip with existing bookings connected to shared resources
- At least one booking without connected resources

**Steps:**
1. Navigate to a trip dashboard with existing bookings
2. Find a participant booking and open its **dropdown menu**
3. Select **"Edit or Add Resource"**
4. Verify the resource selection modal opens showing resources connected to the participant's package
5. Select a **different resource** from the dropdown
6. Verify the **sharing options** update based on the newly selected resource
7. Click **"Confirm New Resource"**
8. Verify no email notification confirmation message appears (no emails sent to customer)
9. Verify the booking's resource assignment is updated in the participant table
10. Open a booking for a package **without connected resources**
11. Verify the system prompts to connect resources in the **trip builder** first

**Expected Result:**
- "Edit or Add Resource" option is available in each booking's dropdown menu
- Resource selection modal shows only resources connected to the participant's booked package
- Changing the resource updates the available sharing options dynamically
- Confirming the new resource updates the booking without sending email to the customer
- Packages without connected resources show a prompt directing to the trip builder

---

### TC-009: Mobile Responsive Rendering of Resource Management

**Description:** Verify that the WeTravel homepage, sign-in dialog, and resource management pages render correctly on mobile viewports with touch-friendly interactions and no console errors.

**Preconditions:**
- Browser viewport set to 375x812 (iPhone X)
- No active session

**Steps:**
1. Set viewport to mobile size **(375x812)**
2. Navigate to `https://pre.wetravel.to/#`
3. Verify the homepage renders with **hamburger menu** (generic labeled "Hamburger Menu") instead of full navigation
4. Click the **hamburger menu icon**
5. Verify a navigation menu opens with all sections
6. Click **"Sign In"** (accessible via hamburger or visible link)
7. Verify the sign-in dialog renders correctly on mobile with all elements usable
8. Verify email input, Next button, and social login buttons are all properly sized for touch
9. Close the dialog
10. Log in with valid credentials
11. Navigate to **Inventory > Resource List**
12. Verify the resource list renders correctly on mobile viewport
13. Navigate to **Inventory > Resource Calendar**
14. Verify the calendar renders with touch-friendly date cells
15. Check for **console errors** during the entire mobile session

**Expected Result:**
- Homepage adapts to mobile viewport with hamburger navigation replacing the full nav bar
- Sign-in dialog is fully functional and properly sized on mobile (375x812)
- All form elements (email input, buttons) are large enough for touch interaction
- Resource List page renders correctly on mobile with all controls accessible
- Resource Calendar is usable on mobile with touch-friendly date cells
- No JavaScript errors in console during mobile rendering

**Test Data:** Viewport: 375x812, URL: `https://pre.wetravel.to/#`

---

### TC-010: Team Member Permissions for Resource Management

**Description:** Verify that team member permissions for resource management are properly enforced: "Manage resources" grants Resource List/Calendar access, "Edit a trip" allows trip builder resource editing, and "Issue refunds and change bookings" allows per-booking resource management.

**Preconditions:**
- Three team member accounts configured with different permissions:
  - Member A: "Manage resources and view resource calendar" only
  - Member B: "Edit a trip" only
  - Member C: "Issue refunds and change bookings" only
- Existing trip with shared resources and bookings

**Steps:**
1. Log in as **Member A** (Manage resources permission)
2. Navigate to **Inventory > Resource List** — verify access is granted
3. Create a new resource — verify action is allowed
4. Edit an existing resource — verify action is allowed
5. Navigate to **Inventory > Resource Calendar** — verify access is granted
6. Log out and log in as **Member B** (Edit a trip permission)
7. Navigate to the **Trip Builder**
8. Verify resource connections can be edited in the pricing section
9. Attempt to access **Inventory > Resource List** directly
10. Verify access is denied or limited
11. Log out and log in as **Member C** (Issue refunds and change bookings)
12. Navigate to the trip dashboard
13. Open a participant booking's dropdown menu
14. Verify resources can be added, edited, and removed for the specific booking

**Expected Result:**
- "Manage resources and view resource calendar" permission grants full access to Resource List and Resource Calendar (create, edit, delete)
- "Edit a trip" permission allows editing resource connections in the trip builder but does not grant Resource List access
- "Issue refunds and change bookings" permission allows resource management at the individual booking level
- Permission boundaries are properly enforced — each role can only perform permitted actions

---

### TC-011: Duplicating Lists Preserves Room Assignments

**Description:** Verify that duplicating an existing rooming list preserves participant room assignments when the same departure date is selected, and that Focus Mode correctly hides full rooms.

**Preconditions:**
- Authenticated trip organizer with Pro plan
- An existing rooming list with participants assigned to rooms
- At least some rooms at full capacity and some with remaining spots

**Steps:**
1. Navigate to the trip dashboard and click **"Lists"**
2. Find an existing list and click its **three-dot menu** (⋮)
3. Click **"Duplicate"**
4. Verify the duplication confirmation modal appears
5. Verify the list name is pre-filled with **"(Copy)"** suffix
6. Rename the list to `"Duplicated Rooming List"`
7. If the trip is recurring, verify the **departure date selector** appears
8. Select the **same date** as the original list
9. Verify the **"Keep Participant Assignments"** option becomes available
10. Toggle **"Keep Participant Assignments"** to enabled
11. Click **"Confirm"** to duplicate
12. Verify the new list is created with all room assignments preserved
13. Click the **"Focus Mode"** toggle
14. Verify full rooms are hidden and only rooms with available spots are shown
15. Verify only unassigned participants remain visible in the participant table

**Expected Result:**
- Duplicate option is available in the list's three-dot menu
- Duplication modal shows name field pre-filled with "(Copy)" suffix
- For recurring trips, date selector allows choosing different departure dates
- When the same date is selected, "Keep Participant Assignments" option becomes available
- Duplicated list preserves all room assignments when option is enabled
- Focus Mode hides full rooms and their assigned participants
- Focus Mode shows only rooms with available spots and unassigned participants

---

### TC-012: Homepage Reachability and Navigation to Resource Management

**Description:** Verify that the WeTravel homepage loads correctly, all navigation elements function, and the path to resource management documentation is reachable through the Help Center.

**Preconditions:**
- No active session required
- Desktop viewport (1280x900)

**Steps:**
1. Navigate to `https://pre.wetravel.to/#`
2. Verify the page loads with title containing **"WeTravel"**
3. Verify the main heading **"The operating system for multi-day travel businesses"** is visible (`getByRole('heading', { level: 1 })`)
4. Verify the navigation bar contains: **Products**, **Solutions**, **Pricing**, **Resources**, **Book a Demo**, **Sign In**
5. Verify the **"Booking and Trip Management"** section text mentions **"room inventory"**
6. Verify the **"Inventory Management"** link is present in the footer under Products
7. Click the **"Inventory Management"** footer link (`getByRole('link', { name: 'Inventory Management' })`)
8. Verify the Inventory Management product page loads at `product.wetravel.com/inventory-management`
9. Navigate back to the homepage
10. Click **"Help Center"** in the footer (`getByRole('link', { name: 'Help Center' })`)
11. Verify the Help Center loads at `help.wetravel.com`
12. Type **"inventory management"** in the search box and press Enter
13. Verify relevant articles appear including "Inventory Management: How-To Guide"

**Expected Result:**
- Homepage loads successfully at `https://pre.wetravel.to/#`
- All navigation elements (Products, Solutions, Pricing, Resources, Book a Demo, Sign In) are present and functional
- "Booking and Trip Management" section references room inventory in its description
- "Inventory Management" footer link navigates to the correct product page
- Help Center is accessible at `help.wetravel.com`
- Searching for "inventory management" returns relevant articles about resource sharing and management

**Test Data:** URL: `https://pre.wetravel.to/#`, Help Center: `https://help.wetravel.com/`

---

**Summary**: 12 test cases covering Happy Path (TC-002, TC-004, TC-007, TC-008), Navigation/State Transitions (TC-004, TC-005, TC-008), Negative/Error Scenarios (TC-003 allocation enforcement, TC-005 delete protection), Edge Cases (TC-006 overbooking, TC-011 list duplication), Accessibility (TC-001 dialog accessibility), Responsive/Runtime Regression (TC-009 mobile viewport), and Reachability/Smoke (TC-012 homepage navigation). All scenarios are independently runnable after splitting. Auth-required tests specify preconditions for valid credentials.