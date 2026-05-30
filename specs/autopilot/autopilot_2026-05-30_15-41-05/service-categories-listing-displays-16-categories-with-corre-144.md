# Test: Service categories listing displays 16 categories with correct service counts

## Description
Validates that /serviceCategories renders a grid of 16 category cards with icons, names, and service counts, and that major categories have the correct counts.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify the page displays a grid of exactly 16 category cards
3. Verify each card shows: category icon, category name, and service count
4. Verify major categories with correct counts: Legal services (96), Taxes (49), Licenses (40), Communal (37), Education (27), Medicine (23)
5. Verify each category card is a clickable link
6. Verify tab navigation is present with Categories tab highlighted as active

## Expected Outcome
- Exactly 16 category cards are displayed
- Major categories show correct service counts matching exploration data
- All category cards are clickable links
- Categories tab is visually active

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-130, REQ-134
- Source flow(s): Browse Services by Category
