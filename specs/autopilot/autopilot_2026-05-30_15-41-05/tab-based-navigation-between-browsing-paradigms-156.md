# Test: Tab-Based Navigation Between Browsing Paradigms

## Description
The system shall provide a consistent tab navigation interface allowing users to switch between three service browsing paradigms: by Organization (Qurumlar), by Field (Sahələr), and by Life Event (Həyat hadisələri).

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Tab-Based Navigation Between Browsing Paradigms

## Expected Outcome
- Three tabs are displayed: Qurumlar, Sahələr, Həyat hadisələri
- Selecting Qurumlar tab navigates to /entities showing the organizations list
- Selecting Sahələr tab navigates to /serviceCategories showing the field categories
- Selecting Həyat hadisələri tab navigates to /lifeEvents showing life event cards
- The currently active tab is visually highlighted
- Tab navigation is consistent across all three browsing pages

## Test Data
- Target URL: https://my.gov.az/serviceCategories
