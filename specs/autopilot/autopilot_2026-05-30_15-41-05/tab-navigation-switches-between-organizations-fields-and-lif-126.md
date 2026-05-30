# Test: Service Browsing by Life Events

## Description
The system shall allow users to browse government services organized by life events/milestones. The Life Events tab must display 11 life event cards, each linking to a detail page with description and related services.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Service Browsing by Life Events

## Expected Outcome
- Life Events page loads at /lifeEvents with Həyat hadisələri tab selected
- 11 life event cards are displayed with icons: Marriage, My child born, Death of family member, Education, Health, Employment, Retirement, Real Estate, Vehicle purchase, Relocate to Azerbaijan, Return to Karabakh
- Breadcrumb shows: Ana səhifə > Xidmətlər
- Clicking a life event card navigates to the life event detail page (e.g., /life-events/{uuid})
- Tab navigation allows switching between Qurumlar, Sahələr, and Həyat hadisələri

## Test Data
- Target URL: https://my.gov.az/serviceCategories
