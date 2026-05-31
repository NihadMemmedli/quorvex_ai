# Test Plan: Package Management

## Application Overview

E2E test scenarios for WeTravel Package Management covering package creation, resource creation, package-to-resource mapping, inventory-driven availability calculation, resource calendar monitoring, and rooming list export.

## Test Scenarios

### 1. Package Management

**Seed:** `/app/tests/generated/seed.spec.ts`

#### 1.1. TC-001: Create Packages for Each Accommodation Option in Trip Builder

**File:** `tests/package-management/tc-001-create-packages.spec.ts`

**Steps:**
  1. Navigate to the WeTravel trip builder page
  2. Click the button to create a new trip
  3. Enter a trip name (e.g., Izmir Week Retreat)
  4. In the packages section, click Add Package
  5. Enter package name Full week program - Double occupancy and set a price
  6. Click Add Package again
  7. Enter package name Full week program - Single occupancy and set a price
  8. Click the Publish button to publish the trip
  9. Navigate to the generated trip page URL
  10. Verify both packages appear on the published trip page

**Expected Results:**
  - Trip builder loads without errors
  - Both packages are created and visible in the package list
  - The published trip page displays both packages as selectable options
  - Each package shows the correct name and price

#### 1.2. TC-002: Create Accommodation Resource with Capacity Settings

**File:** `tests/package-management/tc-002-create-resource.spec.ts`

**Steps:**
  1. Navigate to the Inventory section from the main navigation
  2. Click the Create New Resource button
  3. Enter resource name Izmir - Double rooms
  4. Verify the resource type dropdown defaults to Accommodation
  5. Enter quantity 15 in the quantity field
  6. Enter capacity 2 in the capacity field
  7. Select sharing mode Private only
  8. Click the Save or Create button
  9. Verify the new resource appears in the resource list
  10. Navigate to the trip builder and verify the resource is available in the resource selector

**Expected Results:**
  - Inventory section loads correctly
  - Resource creation form accepts all fields
  - After saving, the resource appears in the resource list with quantity 15 and capacity 2
  - The resource is visible in the trip builder resource dropdown

#### 1.3. TC-003: Connect Resource to Package and Verify Availability Mode Switch

**File:** `tests/package-management/tc-003-connect-resource-package.spec.ts`

**Steps:**
  1. Navigate to the trip builder for the draft trip
  2. Scroll to the Pricing section
  3. Locate the first package (Double occupancy)
  4. Find the Connect resource to package toggle and click Yes
  5. Wait for the resource selector to appear
  6. Select Izmir - Double rooms from the resource dropdown
  7. Verify the availability indicator changes to Based on resources availability
  8. Repeat for the second package (Single occupancy)
  9. Verify both packages display resource-driven availability

**Expected Results:**
  - Pricing section displays Connect resource to package toggle
  - Clicking Yes reveals a resource selector dropdown
  - After selecting a resource availability label changes to Based on resources availability
  - Both packages can be connected to the same resource simultaneously

#### 1.4. TC-004: Restrict Package Availability Below Resource Capacity

**File:** `tests/package-management/tc-004-restrict-package-availability.spec.ts`

**Steps:**
  1. Navigate to the trip builder for the trip with connected resources
  2. Go to the pricing section
  3. Select the Single occupancy package
  4. Locate the package-level availability restriction field
  5. Enter a maximum availability value of 5
  6. Save the changes
  7. Verify the Single occupancy package shows restricted availability of 5
  8. Verify the Double occupancy package still reflects full resource availability

**Expected Results:**
  - Package-level availability restriction field is editable
  - Setting a restriction value of 5 persists correctly
  - The restricted package displays limited availability of 5
  - The other package sharing the same resource is NOT affected

#### 1.5. TC-005: Create Resources with Shared and Private Sharing Options

**File:** `tests/package-management/tc-005-create-shared-resources.spec.ts`

**Steps:**
  1. Navigate to the Inventory section
  2. Click Create New Resource
  3. Enter name Nuqui - Triple room with qty 1 cap 3
  4. Select sharing mode Shared and private
  5. Add sharing option Shared girls with capacity 3
  6. Add sharing option Shared boys with capacity 3
  7. Save and verify the resource appears with 2 sharing options
  8. Click Create New Resource again
  9. Enter name Nuqui - Double queen with qty 10 cap 4
  10. Select sharing mode Shared and private
  11. Add sharing option Shared girls with capacity 4
  12. Add sharing option Shared boys with capacity 4
  13. Add sharing option Shared adults with capacity 2
  14. Save and verify the resource appears with 3 sharing options

**Expected Results:**
  - Shared and private mode is available
  - Multiple sharing options can be added to a single resource
  - Each sharing option has name and capacity fields
  - Resources appear correctly in the list with sharing configurations

#### 1.6. TC-006: Verify Inventory-Based Availability Calculation After Bookings

**File:** `tests/package-management/tc-006-availability-calculation.spec.ts`

**Steps:**
  1. Navigate to the published trip page with connected packages
  2. Record initial availability for both packages
  3. Complete a booking for the Double occupancy package
  4. Refresh the trip page
  5. Verify Double occupancy availability decreased by 1
  6. Verify Single occupancy availability also decreased by 1
  7. Navigate to the Resource Calendar
  8. Verify remaining rooms count reflects the booking

**Expected Results:**
  - Initial availability matches resource capacity of 15
  - After booking availability decrements correctly for both packages
  - Resource Calendar shows accurate remaining room count of 14
  - No manual adjustment needed

#### 1.7. TC-007: Export Rooming List with Resource Assignments

**File:** `tests/package-management/tc-007-export-rooming-list.spec.ts`

**Steps:**
  1. Navigate to the Manage trip page for a trip with bookings
  2. Locate the export section
  3. Click Export to generate the participant export
  4. Wait for export file to download
  5. Open the export file and navigate to the Participant tab
  6. Verify a Resource or Resource Assignment column exists
  7. Verify each participant shows the correct resource assigned

**Expected Results:**
  - Export generation completes without errors
  - Downloaded file contains participant data
  - Participant data includes resource assignment column
  - Resource assignments match package-to-resource connections

#### 1.8. TC-008: Resource Calendar Monitoring of Room Availability

**File:** `tests/package-management/tc-008-resource-calendar.spec.ts`

**Steps:**
  1. Navigate to the Inventory section
  2. Click on Resource Calendar
  3. Wait for calendar to load
  4. Verify all created resources are displayed
  5. Verify each resource shows total capacity and remaining availability
  6. Cross-reference remaining availability with bookings
  7. If calendar supports date navigation test navigation between periods

**Expected Results:**
  - Resource Calendar loads without timeout
  - All created resources appear in the calendar
  - Each resource displays total and remaining availability
  - Availability counts are consistent with bookings

#### 1.9. TC-009: Validate Form Fields and Error States in Resource Creation

**File:** `tests/package-management/tc-009-resource-form-validation.spec.ts`

**Steps:**
  1. Navigate to Inventory section and click Create New Resource
  2. Leave all fields empty and click Save
  3. Verify validation errors appear for required fields
  4. Enter resource name but leave quantity empty and click Save
  5. Verify validation error for quantity
  6. Enter quantity as 0 and click Save
  7. Verify validation rejects zero quantity
  8. Enter quantity as -5 and click Save
  9. Verify validation rejects negative quantity
  10. Enter valid quantity but capacity 0 and click Save
  11. Verify validation rejects zero capacity
  12. Fill all fields correctly and save successfully

**Expected Results:**
  - Empty form shows required field validation errors
  - Zero and negative quantities are rejected
  - Zero capacity is rejected
  - Correctly filled form saves successfully
  - No console errors during validation

#### 1.10. TC-010: Responsive Rendering of Trip Page with Multiple Packages

**File:** `tests/package-management/tc-010-responsive-packages.spec.ts`

**Steps:**
  1. Navigate to published trip page with 5 packages
  2. Verify layout on desktop 1280x800
  3. Resize browser to mobile 375x812
  4. Verify all 5 packages visible and selectable
  5. Verify no horizontal overflow on mobile
  6. Resize to tablet 768x1024
  7. Verify packages render correctly on tablet
  8. Check console for no errors during resize

**Expected Results:**
  - All packages render on desktop tablet and mobile
  - Package selection works on all viewport sizes
  - No overflow on mobile
  - No console errors from viewport changes

#### 1.11. TC-011: Accessibility of Package Selection and Resource Management

**File:** `tests/package-management/tc-011-accessibility.spec.ts`

**Steps:**
  1. Navigate to trip builder pricing section
  2. Verify Connect resource to package toggle has accessible label
  3. Tab through interactive elements and verify logical order
  4. Verify resource selector dropdown has accessible name
  5. Verify availability labels are in accessibility tree
  6. Navigate to Inventory resource list
  7. Verify resource cards have descriptive accessible text
  8. Verify Create New Resource button has accessible name

**Expected Results:**
  - All interactive elements have accessible labels
  - Tab navigation follows logical order
  - Resource selector options are accessible
  - Buttons and toggles have descriptive names

#### 1.12. TC-012: Complex Multi-Resource Scenario with 5 Packages and 4 Room Types

**File:** `tests/package-management/tc-012-complex-multi-resource.spec.ts`

**Steps:**
  1. Navigate to trip builder and create trip Colombia Retreat - Nuqui
  2. Create 5 packages for different accommodation options
  3. Navigate to Inventory and create 4 resources with sharing configs
  4. Connect each package to appropriate resource and sharing option
  5. Verify all 5 packages show Based on resources availability
  6. Publish the trip
  7. Navigate to published trip page
  8. Verify all 5 packages displayed with correct availability
  9. Verify no console errors

**Expected Results:**
  - All 5 packages created successfully
  - 4 resources with sharing configurations saved correctly
  - Each package connected to correct resource and sharing option
  - Published trip page shows all packages with calculated availability
