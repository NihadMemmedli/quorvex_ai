# Test: Create link accessible from different app pages via hamburger menu

## Source
Generated from: `verify-create-link-triggers-trip-creation-flow.md`
Test ID: TC-009
Category: Observed API Endpoints

## Observed Selectors
| Element | Selector | Notes |
|---------|----------|-------|
| Hamburger Menu button | `getByRole('button', { name: 'Hamburger Menu' })` | Opens side navigation |
| Create link (in nav) | `getByRole('link', { name: 'Create' })` | href="#", triggers JS navigation to `/itinerary_builder/create` |
| My Trips link | `getByRole('link', { name: 'My Trips' })` | href="/user/my_trips" |
| Create Trip button | `getByRole('link', { name: 'Create Trip' })` | href="/itinerary_builder/new?skipPaymentLinkValidation=yes" |
| Create Payment Link button | `getByRole('link', { name: 'Create Payment Link' })` | href="/payment_link" |
| Create Request button | `getByRole('link', { name: 'Create Request' })` | href="/payment_request" |
| Sign Out button | `getByRole('button', { name: 'Sign Out' })` | In navigation |
| WeTravel Logo link | `getByRole('link', { name: 'WeTravel Logo' })` | Navigates to homepage |
| Trip Title field | `getByPlaceholder('e.g. Epic Japan Trip!')` | In itinerary builder |
| Destination field | `getByPlaceholder("What's the destination?")` | In itinerary builder |
| Search field | `getByPlaceholder('Search for participants and trips')` | On My Trips page |
| Trip Basics sidebar | `getByRole('link', { name: 'Trip Basics' })` | In builder sidebar |
| Trip Page sidebar | `getByRole('link', { name: 'Trip Page' })` | In builder sidebar |
| Packages sidebar | `getByRole('link', { name: 'Packages' })` | In builder sidebar |
| Add-ons sidebar | `getByRole('link', { name: 'Add-ons' })` | In builder sidebar |
| Participant Info sidebar | `getByRole('link', { name: 'Participant Info' })` | In builder sidebar |
| eSignature sidebar | `getByRole('link', { name: 'eSignature' })` | In builder sidebar |
| Settings sidebar | `getByRole('link', { name: 'Settings' })` | In builder sidebar |
| Preview button | `getByText('Preview')` | In builder sidebar |
| Publish button | `getByText('Publish')` | In builder sidebar |
| Next button | `getByText('Next')` | In builder footer |
| Start verification button | `getByRole('button', { name: 'Start your verification' })` | Account verification alert |
| Upload Document button | `getByRole('button', { name: 'Upload Document' })` | Payment Request builder |
| Create Request submit | `getByRole('button', { name: 'Create Request' })` | Payment Request builder submit |
| Sort combobox | `getByRole('combobox')` (on My Trips) | Sort options for trip list |
| List/Calendar toggle | Clickable generic with text "List" / "Calendar" | View toggle on My Trips |

## Observed URLs
| Page | URL |
|------|-----|
| My Trips | `https://pre.wetravel.to/user/my_trips?view=List` |
| Create Hub | `https://pre.wetravel.to/itinerary_builder/create` |
| Itinerary Builder (new) | `https://pre.wetravel.to/itinerary_builder/new?skipPaymentLinkValidation=yes` |
| Itinerary Builder (trip basics) | `https://pre.wetravel.to/itinerary_builder/{id}#/builder/trip-basics` |
| Payment Link Builder | `https://pre.wetravel.to/payment_link/{id}/builder` |
| Payment Request Builder | `https://pre.wetravel.to/payment_request/{id}/builder` |

## Description
** Verify that the "Create" link in the hamburger navigation menu is accessible and functional from multiple pages in the application, not just My Trips.

## Preconditions
- **
- User is logged in

## Steps

1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Open hamburger menu, verify "Create" link is present, close menu
3. Navigate to `https://pre.wetravel.to/user/itineraries`
4. Open hamburger menu: `getByRole('button', { name: 'Hamburger Menu' })`
5. Verify the "Create" link is visible in the navigation
6. Click "Create": `getByRole('link', { name: 'Create' })`
7. Verify navigation to `/itinerary_builder/create`
8. Navigate to `https://pre.wetravel.to/user/payments/balance`
9. Open hamburger menu and verify "Create" link is present
10. Click "Create" and verify navigation to `/itinerary_builder/create`

## Expected Outcome

- The "Create" link is consistently available in the hamburger navigation from all app pages
- Clicking "Create" from any page navigates to `/itinerary_builder/create`
- The creation hub page loads correctly regardless of the referring page
