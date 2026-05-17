# Test: Help & Support page meets basic accessibility requirements for tabs and accordion

## Description
Validates that the FAQ tab list, category chips, and accordion items expose proper ARIA roles/states so they are keyboard- and screen-reader accessible.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/support
2. Inspect the FAQ/Contact tab controls and verify they expose role='tab' with aria-selected reflecting the active tab
3. Use the Tab key to move focus to the category chips and verify focus is visible
4. Press Enter/Space on a category chip and verify the FAQ list updates
5. Use the Tab key to focus an FAQ accordion item and verify aria-expanded toggles when activated with Enter/Space

## Expected Outcome
- Tabs expose role='tab' with correct aria-selected state
- Category chips and FAQ items are reachable via keyboard with visible focus indicators
- Accordion items expose aria-expanded that toggles on activation

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-084, REQ-085, REQ-086, REQ-087
- Source flow(s): Browse Help/FAQ by Category, Access Help and Support Contact (synthesized)
