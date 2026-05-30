# Test: Service Detail Page Display

## Description
The system shall provide a detailed service page for each government e-service showing the service description, pricing information, step-by-step process, and an apply button.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Service Detail Page Display

## Expected Outcome
- Service detail page is accessible via URL (e.g., /services/marriage-registration?serviceLabel=MR)
- Breadcrumb navigation shows the full path: Home > Services > {Entity Name} > {Service Name}
- Service description text is displayed
- Pricing table shows all applicable fees (e.g., 20 AZN medical exam + 10 AZN state fee for marriage registration)
- A numbered steps table describes the application process (e.g., 4 steps)
- Alert banners for special requirements are displayed (e.g., medical examination requirement)
- An 'Apply' button (MÜRACİƏT ET) is prominently displayed
- A FAQ tab is available for the service

## Test Data
- Target URL: https://my.gov.az/serviceCategories
