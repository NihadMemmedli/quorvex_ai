# Test: Entity breadcrumb on service detail navigates to ministry catalog with 35 services

## Description
Validates breadcrumb navigation from a service detail page back to its owning entity and that the entity page lists the full ministry catalog.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/services/retirement-calculator
2. Locate the entity breadcrumb labeled 'Ministry of Labour and Social Protection'
3. Click the entity breadcrumb
4. Wait for navigation to the entity detail page

## Expected Outcome
- URL navigates to /en/entities/{entity_id} (observed: add63f11-...)
- Entity detail page renders the Ministry of Labour and Social Protection catalog
- Entity page lists 35 services

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-068, REQ-077
- Source flow(s): Service to Entity breadcrumb navigation
