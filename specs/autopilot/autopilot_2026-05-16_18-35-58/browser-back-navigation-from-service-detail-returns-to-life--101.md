# Test: Browser back navigation from service detail returns to life-event page

## Description
Validates that after navigating to the Power of Attorney Termination service detail page, using the browser back button returns the user to the originating life-event detail page with state preserved.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/life-events/1b72c5b6-dcc6-415c-81bd-f8e23869b10c
2. Click the link labeled 'Etibarnaməyə xitam ərizəsi'
3. Wait for the service detail page to load
4. Trigger browser back navigation
5. Verify the user returns to the life-event detail page

## Expected Outcome
- The browser returns to /life-events/1b72c5b6-dcc6-415c-81bd-f8e23869b10c
- The life-event page renders successfully on back navigation
- The 'Etibarnaməyə xitam ərizəsi' link remains visible after returning

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-080
- Source flow(s): Navigate to Power of Attorney Termination Service (synthesized)
