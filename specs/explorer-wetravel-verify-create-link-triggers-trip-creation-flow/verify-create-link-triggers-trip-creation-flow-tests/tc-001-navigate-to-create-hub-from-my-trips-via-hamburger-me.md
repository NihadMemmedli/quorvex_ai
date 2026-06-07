# Test: Navigate to Create hub from My Trips via hamburger menu Create link

## Source
Generated from: `verify-create-link-triggers-trip-creation-flow.md`
Test ID: TC-001
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
** Verify that clicking the "Create" link in the hamburger navigation menu on the My Trips page navigates the user to the trip creation hub page.

## Preconditions
- **
- User is logged in to WeTravel at https://pre.wetravel.to
- User is on the My Trips page (`/user/my_trips`)

## Steps

1. Navigate to `https://pre.wetravel.to/user/my_trips`
2. Click the hamburger menu button: `getByRole('button', { name: 'Hamburger Menu' })`
3. Verify the navigation menu opens and the "Create" link is visible
4. Click the "Create" link: `getByRole('link', { name: 'Create' })`

## Expected Outcome

- The page navigates to `https://pre.wetravel.to/itinerary_builder/create`
- The creation hub page is displayed with two sections: "Sell to Travelers" and "Collect from Business Partners"
- Three creation option cards are visible: "Full Trip", "Payment Link", and "Business Payment Request"
- Each card has a corresponding action link: "Create Trip", "Create Payment Link", "Create Request"
- No blocking JavaScript errors in the console (Sentry 429 errors are acceptable)
