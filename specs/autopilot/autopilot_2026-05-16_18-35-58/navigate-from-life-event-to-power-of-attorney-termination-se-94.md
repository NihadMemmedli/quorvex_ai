# Test: Navigate from life-event to Power of Attorney Termination service detail page

## Description
Validates the observed primary navigation flow: clicking the 'Etibarnaməyə xitam ərizəsi' link from the life-event detail page lands the user on the correct service detail page with the AFTOPOA service label preserved.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/life-events/1b72c5b6-dcc6-415c-81bd-f8e23869b10c
2. Click the link labeled 'Etibarnaməyə xitam ərizəsi'
3. Wait for navigation to complete
4. Verify the destination URL contains '/services/etibranameye-xitam-erizesi' and 'serviceLabel=AFTOPOA'

## Expected Outcome
- The browser navigates to /services/etibranameye-xitam-erizesi?serviceLabel=AFTOPOA
- The 'serviceLabel=AFTOPOA' query parameter is preserved in the final URL
- The service detail page loads successfully and renders associated content

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-080, REQ-081
- Source flow(s): Navigate to Power of Attorney Termination Service (synthesized)
