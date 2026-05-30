# Test: Life Events listing page loads and displays navigable event cards

## Description
Validates that the /lifeEvents page renders a grid of life event cards (Marriage, Having a child, Education, etc.) and that tab navigation is present with Entities, Categories, and Life Events tabs.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/lifeEvents
2. Verify the page loads without errors
3. Verify a grid of life event cards is displayed including at minimum: Marriage (Ailə qurmaq), Having a child (Valideyn olmaq), Education (Təhsil almaq), Health (Sağlamlıq), Employment (Məşğulluq)
4. Verify three tab navigation links are present: Qurumlar (Entities), Sahələr (Categories), Life Events
5. Verify the Life Events tab is visually highlighted as active
6. Verify each life event card is a clickable link

## Expected Outcome
- Life Events page loads with HTTP 200
- At least 5 life event cards are visible in a grid layout
- Three navigation tabs are present and Life Events tab is active
- Each card has a clickable link pointing to /life-events/{uuid}

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-121, REQ-134
- Source flow(s): Browse Life Event Services and Attempt to Apply
