# Test: Service List Display by Category

## Description
The system shall display all individual government services within a selected category. Each service must show its title, icon, links to legal acts, instruction PDFs, and any electronic signature requirements.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Service List Display by Category

## Expected Outcome
- Navigating to a category (e.g., Social Protection /serviceCategories/01e3a9be-...) displays all services in that category
- Breadcrumb navigation shows: Ana səhifə > Xidmətlər > [Category Name]
- Each service card displays: title, icon, and action buttons
- Legal act links (Huquqi aktlar) are available per service
- Instruction links (PDF documents from e-gov.az) are available per service
- Services requiring electronic signature display a badge indicating Sima token or Asan İmza requirement
- Video tutorial links are shown on services that have them
- Last update date is displayed on the page
- Clicking a service link navigates to the service detail page (e.g., /services/retirement-calculator?serviceLabel=RC)

## Test Data
- Target URL: https://my.gov.az/serviceCategories
