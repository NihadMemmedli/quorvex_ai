# Test: Service URL with invalid serviceLabel returns a graceful fallback

## Description
Validates that the /services/ path with an invalid or unknown serviceLabel query parameter returns a user-friendly fallback rather than an unhandled exception.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/services/etibranameye-xitam-erizesi?serviceLabel=INVALID_LABEL_XYZ
2. Wait for the page to render
3. Verify the page handles the invalid label gracefully

## Expected Outcome
- A user-friendly error or fallback message is displayed
- No raw stack traces or server errors are exposed
- The application does not crash or return an unhandled 5xx

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-083
