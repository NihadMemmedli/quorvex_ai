# Test: Browse government services by category from service categories page

## Description
Validates that a user can land on /serviceCategories, see 16 category cards with icons and service counts, click into a specific category (e.g., Social Protection), and view the filtered service list with breadcrumb navigation.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Sahələr tab is selected by default
3. Verify 16 service category cards are displayed with icons, titles, and service counts
4. Click 'Sosial müdafiə, sosial təminat' (Social Protection) category card
5. Verify URL navigates to /serviceCategories/{uuid}
6. Verify breadcrumb shows: Ana səhifə > Xidmətlər > [Category Name]
7. Verify individual service cards are displayed with titles, icons, and action buttons

## Expected Outcome
- Sahələr tab is visually highlighted as active
- 16 category cards are rendered with visible service counts
- Clicking a category navigates to the correct filtered service list page
- Breadcrumb correctly reflects navigation hierarchy

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-092, REQ-093
- Source flow(s): Apply for Government Service, Navigation: service_categories to login (inferred)
