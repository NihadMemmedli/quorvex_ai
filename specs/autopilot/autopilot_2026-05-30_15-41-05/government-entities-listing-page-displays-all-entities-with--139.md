# Test: Government entities listing page displays all entities with service counts

## Description
Validates that the /entities page displays a grid of 30+ government entity cards, each with an icon, name, and service count, and that tab navigation allows switching between views.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities
2. Verify the page displays a grid of entity cards
3. Verify at least 30 entity cards are displayed
4. Verify major ministry cards are present: Ministry of Labor (35 services), Ministry of Digital Development (73 services), Ministry of Economy (82 services), Ministry of Justice (29 services), Ministry of Health (24 services)
5. Verify each card shows an entity icon, name, and service count
6. Verify tab navigation with Entities tab visually highlighted as active
7. Click the 'Sahələr' (Categories) tab and verify navigation to /serviceCategories
8. Click the 'Life Events' tab and verify navigation to /lifeEvents

## Expected Outcome
- At least 30 entity cards are visible
- Each card contains icon, name, and numeric service count
- Major ministry entities are present with correct service counts
- Tab switching navigates to the correct pages

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-125, REQ-134
- Source flow(s): Browse Government Entity Services
