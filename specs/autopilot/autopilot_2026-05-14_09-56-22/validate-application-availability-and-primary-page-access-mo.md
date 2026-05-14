# Test: Validate Application availability and primary page access mobile rendering

## Description
Checks responsive rendering for Application availability and primary page access.

## Prerequisites
- Fresh browser session

## Steps
1. Set viewport to a mobile size
2. Navigate to https://my.gov.az/en/entities
3. Wait for the page to finish loading
4. Verify the primary content is visible without horizontal overflow

## Expected Outcome
- Primary content remains visible on mobile
- No major layout overlap blocks interaction

## Test Data
- Target URL: https://my.gov.az/en/entities

## Source Evidence
- Source requirement(s): REQ-013
