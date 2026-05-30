# Test: Navigation from Life Event to Service Application

## Description
The system shall allow users to navigate from a life event detail page directly to a related service's application page via linked service entries.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Verify Navigation from Life Event to Service Application

## Expected Outcome
- Life event detail page displays a list of related e-services as clickable links
- Clicking a related service link navigates to the corresponding service detail page (e.g., /services/marriage-registration?serviceLabel=MR)
- The navigation preserves the service label query parameter
- The service detail page loads with full service information

## Test Data
- Target URL: https://my.gov.az/serviceCategories
