# Test Plan: Resource Inventory (Accommodations)

This test plan covers the WeTravel Resource Inventory feature for managing accommodation resources, connecting them to packages, monitoring availability, and exporting rooming lists.

---

## TC-001: Navigate to Inventory Section and Verify Resource List Page

**Description:** Verify the Inventory section loads correctly with resource list and creation controls.

**Preconditions:**
- User is logged in to WeTravel dashboard
- At least one trip exists in the system

**Steps:**
1. Navigate to the WeTravel dashboard
2. Click on the "Inventory" section in the navigation menu
3. Verify the Inventory page loads with the resource list area visible
4. Verify the "Create New Resource" button is present and accessible
5. Verify the page heading or title mentions "Inventory" or "Resources"

**Expected Result:**
- Inventory section page loads without errors
- Resource list area is visible and displays any existing resources
- "Create New Resource" button is visible and clickable
- No console errors on page load

---

## TC-002: Create New Private Accommodation Resource (Simple Scenario)

**Description:** Create a private-only accommodation resource with name, quantity, and capacity fields, verifying it appears in both the resource list and trip builder.

**Preconditions:**
- User is logged in to WeTravel dashboard
- User has access to the Inventory section
- A published trip exists (e.g., Izmir trip)

**Steps:**
1. Navigate to the Inventory section
2. Click the "Create New Resource" button
3. Verify the resource creation form or modal appears
4. Enter "Izmir - Double rooms" into the resource name field
5. Verify the resource type defaults to "Accommodation"
6. Enter "15" into the quantity field
7. Enter "2" into the capacity field
8. Select "Private only" as the resource sharing configuration
9. Click the "Create" or "Save" button to submit the resource
10. Verify the new resource "Izmir - Double rooms" appears in the resource list
11. Verify the resource details show quantity 15 and capacity 2
12. Navigate to the Trip Builder and verify the resource appears in the resource selection list

**Expected Result:**
- Resource creation form opens successfully
- All fields are populated correctly
- Resource type defaults to Accommodation
- Resource is created and appears in the resource list with correct details
- Resource name "Izmir - Double rooms" is displayed
- Resource is available in the trip builder resource selection

---

## TC-003: Create Shared Accommodation Resource with Multiple Sharing Options

**Description:** Create a shared-and-private accommodation resource with multiple named sharing options, each with its own capacity configuration.

**Preconditions:**
- User is logged in to WeTravel dashboard
- User has access to the Inventory section

**Steps:**
1. Navigate to the Inventory section
2. Click the "Create New Resource" button
3. Enter "Nuqui - Double queen" in the resource name field
4. Set quantity to "10"
5. Set capacity to "4"
6. Select "Shared and private" as the resource sharing configuration
7. Add a sharing option with name "Shared girls" and capacity "4"
8. Add a sharing option with name "Shared boys" and capacity "4"
9. Add a sharing option with name "Shared adults" and capacity "2"
10. Click "Create" to save the resource
11. Verify the resource appears in the resource list with all three sharing options
12. Verify the resource shows "Shared and private" configuration label

**Expected Result:**
- Resource creation form allows adding multiple sharing options
- Each sharing option can have its own name and capacity
- Resource is created with all three sharing options visible
- Resource list shows the correct sharing configuration
- No errors during multi-option creation

---

## TC-004: Create Multiple Room Type Resources (Complex Scenario)

**Description:** Create four different accommodation resources with varying configurations (private and shared) to model a complex multi-room-type retreat scenario.

**Preconditions:**
- User is logged in to WeTravel dashboard
- A published Colombia retreat trip exists

**Steps:**
1. Navigate to the Inventory section
2. Create resource "Nuqui - Double rooms" with quantity 5, capacity 2, set to "Private only"
3. Verify the first resource appears in the resource list
4. Create resource "Nuqui - Single rooms" with quantity 4, capacity 1, set to "Private only"
5. Verify the second resource appears in the resource list
6. Create resource "Nuqui - Triple room" with quantity 1, capacity 3, set to "Shared and private" with sharing options "Shared girls" (capacity 3) and "Shared boys" (capacity 3)
7. Verify the third resource appears in the resource list with sharing options
8. Create resource "Nuqui - Double queen" with quantity 10, capacity 4, set to "Shared and private" with sharing options "Shared girls" (capacity 4), "Shared boys" (capacity 4), and "Shared adults" (capacity 2)
9. Verify the fourth resource appears in the resource list with sharing options
10. Verify all 4 resources are listed in the Inventory section
11. Navigate to the Trip Builder and verify all 4 resources appear in the resource selection

**Expected Result:**
- All 4 resources are created successfully
- Resource list shows all 4 resources with correct details
- Each resource displays correct name, quantity, and capacity
- Shared resources display their sharing options correctly
- All resources are available in the trip builder
- No errors or data loss when creating multiple resources in sequence

---

## TC-005: Connect Single Resource to Package (Simple Scenario)

**Description:** Connect a single accommodation resource to each of two packages (double occupancy and single occupancy) and verify availability switches to resource-based.

**Preconditions:**
- User is logged in to WeTravel dashboard
- A published Izmir trip exists with two packages: "Full week program - Double occupancy" and "Full week program - Single occupancy"
- Resource "Izmir - Double rooms" (quantity 15, capacity 2, Private only) has been created

**Steps:**
1. Navigate to the Trip Builder for the Izmir trip
2. Locate the Pricing section for the "Full week program - Double occupancy" package
3. Find the "Connect resource to package?" toggle or question
4. Click "Yes" to enable resource connection
5. Verify the list of available resources appears
6. Select "Izmir - Double rooms" from the resource list
7. Verify the resource is connected to the package
8. Verify the package availability label changes to "Based on resources availability"
9. Repeat steps 2-8 for the "Full week program - Single occupancy" package
10. Verify both packages show "Based on resources availability" status

**Expected Result:**
- Resource connection toggle/question appears in the Pricing section
- Resource list appears when connection is enabled
- Selected resource is connected to each package
- Availability mode changes to "Based on resources availability" for both connected packages
- Both packages correctly show resource-based availability

---

## TC-006: Connect Multiple Resources to a Single Package

**Description:** Connect more than one accommodation resource (with sharing options) to a single package, verifying multi-resource package configuration works correctly.

**Preconditions:**
- User is logged in to WeTravel dashboard
- A published Colombia retreat trip exists with 5 packages including "Full week program for girls with shared room (3 to 4 girls per room)"
- Resources "Nuqui - Triple room" and "Nuqui - Double queen" have been created with "Shared girls" sharing options

**Steps:**
1. Navigate to the Trip Builder for the Colombia retreat trip
2. Locate the Pricing section for "Full week program for girls with shared room"
3. Click "Yes" to "Connect resource to package?"
4. Select "Nuqui - Triple room" with the "Shared girls" sharing option
5. Verify the first resource is connected with correct sharing option
6. Add a second resource connection selecting "Nuqui - Double queen" with "Shared girls" sharing option
7. Verify both resources are connected to this single package
8. Verify the package availability changes to "Based on resources availability"
9. Verify that the "Shared girls" sharing option is correctly matched for both resource connections

**Expected Result:**
- Multiple resources can be connected to a single package
- Each resource connection can specify a sharing option
- Package availability switches to resource-based after connection
- All connected resources contribute to package availability calculation
- Sharing options are correctly matched per resource connection
- A specific room can only be booked by one sharing configuration at a time

---

## TC-007: Restrict Package Availability After Resource Connection

**Description:** Apply a package-level availability cap that is lower than the total resource quantity, ensuring inventory is reserved for other package types.

**Preconditions:**
- User is logged in to WeTravel dashboard
- Izmir trip exists with both packages connected to "Izmir - Double rooms" (quantity 15)
- Resources are connected to both "Double occupancy" and "Single occupancy" packages

**Steps:**
1. Navigate to the Trip Builder for the Izmir trip
2. Locate the "Full week program - Single occupancy" package in the Pricing section
3. Find the availability restriction or cap setting for this package
4. Set a maximum availability limit of "5" for this specific package
5. Verify the single occupancy package availability is now capped at 5
6. Verify the double occupancy package still has access to remaining rooms
7. Verify the total availability does not exceed 15 (the resource quantity)
8. Navigate to the Resource Calendar and verify restricted allocation is reflected

**Expected Result:**
- Package-level availability restriction can be set independently of total resource quantity
- Restricted package shows correct capped availability (5 instead of 15)
- Other packages sharing the same resource maintain their own availability
- Resource calendar shows correct remaining inventory accounting for restrictions
- Total booked rooms across all packages cannot exceed the resource quantity

---

## TC-008: Resource Calendar View and Availability Monitoring

**Description:** Access and verify the Resource Calendar displays remaining room inventory across dates, updates with bookings, and reflects resource configurations accurately.

**Preconditions:**
- User is logged in to WeTravel dashboard
- At least one trip with connected resources and existing bookings exists
- Resources have been connected to packages with availability set

**Steps:**
1. Navigate to the Inventory section or trip management area
2. Locate and click on "Resource Calendar"
3. Verify the calendar view loads displaying dates and inventory counts
4. Verify the calendar shows remaining room counts for each date
5. Verify different resource types are distinguishable in the calendar view
6. Identify dates with bookings and verify remaining counts are accurate
7. Verify dates where all rooms are booked show as unavailable or zero remaining
8. Verify the calendar correctly accounts for package-level restrictions
9. Navigate between different date ranges (weeks/months) in the calendar

**Expected Result:**
- Resource Calendar loads without errors
- Calendar displays dates with remaining room inventory per resource
- Remaining counts accurately decrease as bookings are processed
- Different resource types are distinguishable in the calendar
- Fully booked dates show as unavailable
- Calendar correctly accounts for package-level restrictions
- Calendar navigation between date ranges works smoothly

---

## TC-009: Rooming List Export from Manage Trip

**Description:** Generate a rooming list export from the Manage Trip page and verify it includes participant resource assignments and sharing option details.

**Preconditions:**
- User is logged in to WeTravel dashboard
- A trip with existing participant bookings exists
- Resources have been connected to packages
- Participants have been assigned rooms through the booking process

**Steps:**
1. Navigate to the "Manage trip" page for a trip with existing bookings
2. Locate the export section or button
3. Click to generate/export the rooming list
4. Verify the export initiates or the file downloads
5. Open or inspect the exported rooming list content
6. Verify the participant tab includes the resource assigned to each participant
7. Verify participants in shared rooms show their assigned sharing option
8. Verify each participant has a resource and room assignment listed
9. Verify the export format is usable (CSV, Excel, or PDF as applicable)
10. Verify participant data is complete (name, resource, sharing option)

**Expected Result:**
- Rooming list export is accessible from the Manage Trip page
- Export completes successfully without errors
- Exported data includes participant names and assigned resources
- Participants in shared accommodations show their sharing option (e.g., "Shared girls", "Shared adults")
- All participants are accounted for in the export
- Export file is in a readable and usable format
- No participant is missing a resource assignment

---

## TC-010: Resource List Page Navigation and State Transitions

**Description:** Verify navigation between the Inventory resource list, resource detail view, and Trip Builder maintains data integrity and provides smooth state transitions.

**Preconditions:**
- User is logged in to WeTravel dashboard
- Multiple resources have been created in the Inventory section
- A published trip exists in the Trip Builder

**Steps:**
1. Navigate to the Inventory section
2. Verify the resource list displays all created resources
3. Click on a resource entry to view its details
4. Verify the resource detail view shows name, type, quantity, capacity, and sharing options
5. Click back to the resource list
6. Verify the list still shows all resources correctly
7. Navigate to the Trip Builder
8. Verify resources appear in the trip builder resource selection dropdown
9. Navigate back to the Inventory section
10. Verify the Inventory page loads correctly with all resources
11. Use browser back button to return to Trip Builder
12. Use browser forward button to return to Inventory
13. Verify no data loss, console errors, or corrupted state during all navigations

**Expected Result:**
- Resource list page loads consistently with all resources
- Resource detail view displays all configured properties (name, type, quantity, capacity, sharing config)
- Navigation between Inventory and Trip Builder preserves resource data
- Browser back/forward navigation works without errors or data loss
- No state corruption during page transitions
- Resource selection in Trip Builder reflects current resource list

---

## TC-011: Resource Creation Validation and Error Handling

**Description:** Verify form validation prevents creating resources with missing or invalid data, and that appropriate error messages are displayed.

**Preconditions:**
- User is logged in to WeTravel dashboard
- User has access to the Inventory section

**Steps:**
1. Navigate to the Inventory section
2. Click "Create New Resource"
3. Leave all fields empty and click "Create"
4. Verify validation error appears for the required resource name field
5. Enter a resource name but leave quantity field empty
6. Click "Create" and verify validation error for the quantity field
7. Enter a resource name and quantity but leave capacity empty
8. Click "Create" and verify validation error for the capacity field
9. Enter a quantity of "0" or a negative number
10. Verify validation prevents creating a resource with invalid quantity
11. Enter all valid fields (name, quantity > 0, capacity > 0) and verify the resource is created successfully
12. Attempt to create a resource with the same name as an existing resource
13. Verify duplicate name handling (error message or auto-disambiguation)

**Expected Result:**
- Required field validation works for name, quantity, and capacity
- Appropriate error messages are displayed for each missing required field
- Zero or negative quantity values are rejected with a validation message
- Valid resource creation succeeds after fixing all validation errors
- Duplicate resource names are handled appropriately (error or warning)
- No partial resource is created when validation fails
- Form preserves entered values when validation fails (user does not lose work)

---

## TC-012: Responsive Rendering of Inventory Pages

**Description:** Verify that the Inventory section, Resource Calendar, and resource creation forms render correctly across desktop, tablet, and mobile viewport sizes.

**Preconditions:**
- User is logged in to WeTravel dashboard
- Resources have been created in the Inventory section
- A trip with connected resources exists

**Steps:**
1. Set browser viewport to desktop size (1920x1080)
2. Navigate to the Inventory section
3. Verify all resource list columns and action buttons are visible
4. Open the Resource Calendar and verify it renders properly at desktop size
5. Resize browser to tablet viewport (768x1024)
6. Verify the Inventory page renders without horizontal scroll
7. Verify the "Create New Resource" button remains accessible
8. Verify the Resource Calendar adapts to the tablet viewport
9. Resize browser to mobile viewport (375x667)
10. Verify the Inventory page adapts to mobile layout (stacked or scrollable)
11. Verify resources are still readable and actionable on mobile
12. Click "Create New Resource" on mobile and verify the form is usable
13. Navigate to the Resource Calendar on mobile viewport
14. Verify the calendar is viewable and navigable on small screens
15. Check browser console for any JavaScript errors during viewport resizing

**Expected Result:**
- Desktop view (1920x1080) displays all inventory features with full layout
- Tablet view (768x1024) renders without horizontal scrolling issues
- Mobile view (375x667) adapts layout for small screens with readable content
- "Create New Resource" button is accessible and functional at all viewport sizes
- Resource Calendar is viewable and navigable on mobile devices
- Resource creation form is usable on mobile viewport
- No JavaScript console errors during viewport resizing
- No overlapping elements or truncated text at any viewport size

---

## Coverage Summary

| Category | Test Cases |
|---|---|
| **Happy Path** | TC-002, TC-003, TC-004, TC-005, TC-006, TC-007, TC-008, TC-009 |
| **Navigation/State Transitions** | TC-010 |
| **Negative/Error Scenarios** | TC-011 |
| **Edge Cases** | TC-006 (multi-resource), TC-007 (restriction cap) |
| **Accessibility** | TC-001 (UI element checks) |
| **Responsive/Runtime Regression** | TC-012 |
| **Page Reachability** | TC-001 |

**Total Scenarios: 12**