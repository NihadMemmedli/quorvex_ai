# Test: User can switch to the Contact (Əlaqə) sub-tab and back to FAQ

## Description
Validates that the Contact tab switches the view to display contact channels and that the user can return to the FAQ tab.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/support
2. Verify the FAQ tab is selected by default
3. Click the 'Əlaqə' (Contact) sub-tab
4. Verify the Contact view is displayed with contact information/options
5. Click the 'Tez-tez verilən suallar' (FAQ) sub-tab
6. Verify the FAQ list is displayed again with category chips

## Expected Outcome
- Clicking the Contact tab switches the active view
- Contact information/options are rendered when the Contact tab is active
- Clicking the FAQ tab returns to the FAQ list view
- Active tab state updates accordingly when switching

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-087, REQ-084
- Source flow(s): Access Help and Support Contact (synthesized)
