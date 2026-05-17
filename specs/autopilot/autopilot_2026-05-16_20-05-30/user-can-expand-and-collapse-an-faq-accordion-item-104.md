# Test: User can expand and collapse an FAQ accordion item

## Description
Validates the accordion interaction: clicking an FAQ item expands it to show its answer, and clicking again collapses it.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/support
2. Wait for the FAQ list to render
3. Click the first FAQ accordion item
4. Verify the item expands and its detailed answer text becomes visible
5. Click the same FAQ item again
6. Verify the item collapses and its answer is no longer visible
7. Click a different FAQ item
8. Verify it expands independently

## Expected Outcome
- Clicking an FAQ item toggles its expanded/collapsed state
- Answer content is visible when the item is expanded
- Answer content is hidden when the item is collapsed
- Multiple FAQ items can be browsed sequentially

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-086
- Source flow(s): Expand FAQ Item for Detailed Answer (synthesized), Browse Help/FAQ by Category
