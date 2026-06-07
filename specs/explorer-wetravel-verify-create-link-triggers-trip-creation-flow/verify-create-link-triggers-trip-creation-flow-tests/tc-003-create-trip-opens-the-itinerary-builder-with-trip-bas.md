# Test: Create Trip opens the Itinerary Builder with Trip Basics form

## Source
Generated from: `verify-create-link-triggers-trip-creation-flow.md`
Test ID: TC-003
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
** Verify that clicking "Create Trip" on the creation hub page opens the Itinerary Builder with the Trip Basics form pre-loaded.

## Preconditions
- **
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

## Steps

1. Click the "Create Trip" link: `getByRole('link', { name: 'Create Trip' })`
2. Verify the URL changes to `/itinerary_builder/{id}#/builder/trip-basics`
3. Verify the left sidebar is visible with navigation links: Trip Basics (active), Trip Page, Packages, Add-ons, Participant Info, eSignature, Settings
4. Verify the "Trip Title" textbox is present: `getByPlaceholder('e.g. Epic Japan Trip!')`
5. Verify the "Destination" textbox is present: `getByPlaceholder("What's the destination?")`
6. Verify the "Trip is Offered" dropdown is present with default value "One Time"
7. Verify Start Date and End Date fields are present
8. Verify the Group Size section with Min and Max fields
9. Verify the visibility options "Private" and "Public" are displayed
10. Verify the sidebar shows "Preview" and "Publish" options
11. Verify the "3 steps left before you can publish" message is visible
12. Verify the "Saved as draft" status is shown in the footer

## Expected Outcome

- The Itinerary Builder opens with the Trip Basics form
- All expected form fields are rendered and interactive
- The sidebar navigation highlights "Trip Basics" as active
- A draft trip is auto-created (API call to `POST /v1/draft_trips` returns 201)
- Auto-save status indicator is visible
