# Test: Help & Support page loads with FAQ hub and both sub-tabs

## Description
Validates that the /support page is reachable and renders the core FAQ hub structure (heading, FAQ tab selected by default, Contact tab visible, last-updated date).

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/support
2. Wait for the page to finish loading
3. Verify the heading 'Kömək və dəstək' is visible
4. Verify the 'Tez-tez verilən suallar' (FAQ) sub-tab is visible and selected by default
5. Verify the 'Əlaqə' (Contact) sub-tab is visible
6. Verify a last-updated date is displayed on the page

## Expected Outcome
- Page loads successfully (HTTP 200)
- Heading 'Kömək və dəstək' is rendered
- FAQ tab is the active/selected tab on initial load
- Both sub-tabs (FAQ, Əlaqə) are visible
- A last-updated date string is displayed

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-084
- Source flow(s): Browse Help/FAQ by Category
