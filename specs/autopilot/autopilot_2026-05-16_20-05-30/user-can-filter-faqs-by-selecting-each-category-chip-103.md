# Test: User can filter FAQs by selecting each category chip

## Description
Validates the category filter behavior: all six predefined chips are present, clicking a chip filters the FAQ list, the selected chip is highlighted, and switching categories does not require a page reload.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/support
2. Verify the six category chips are visible: 'Ümumi', 'Məlumatlarım', 'mygov ID', 'Rəqəmsal razılıq', 'mygov Checker', 'Həyat hadisələri'
3. Click the 'mygov ID' chip
4. Verify the chip becomes visually highlighted (selected state)
5. Verify the FAQ list updates to show only mygov ID items without a full page reload
6. Click the 'Rəqəmsal razılıq' chip
7. Verify the previously selected chip is no longer highlighted and the new chip is selected
8. Verify the FAQ list updates accordingly

## Expected Outcome
- All 6 category chips are rendered
- Selected chip has a distinct active styling
- FAQ list content changes when a different category is selected
- No full-page navigation occurs (URL remains /support)
- FAQ items remain interactive after filtering

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-085
- Source flow(s): Browse Help/FAQ by Category
