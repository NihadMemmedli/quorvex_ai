# Test: Create Payment Link opens the Payment Link Builder

## Source
Generated from: `verify-create-link-triggers-trip-creation-flow.md`
Test ID: TC-004
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
** Verify that clicking "Create Payment Link" on the creation hub page opens the Payment Link builder form with all expected fields.

## Preconditions
- **
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

## Steps

1. Click the "Create Payment Link" link: `getByRole('link', { name: 'Create Payment Link' })`
2. Verify the URL changes to `/payment_link/{id}/builder`
3. Verify the "Title" textbox is present with placeholder "Epic Japan Trip Payment Link"
4. Verify the "Trip ID" textbox is present with placeholder "ZXN-121"
5. Verify the "Trip Dates" field with start/end date is present
6. Verify the "Amount" textbox is present
7. Verify the currency dropdown is present with "USD" selected by default
8. Verify the "Add Deposit / Payment Plan" toggle (Yes/No) is present
9. Verify the "Add Expiration Date" toggle (Yes/No) is present
10. Verify the "Who pays the fees?" section with Organizer/Participant options
11. Verify the "Publish" button is present: `getByRole('button', { name: 'Publish' })`
12. Verify "Saved as draft" status text is visible

## Expected Outcome

- The Payment Link builder opens with all form fields
- Title, Trip ID, Dates, Amount, and Currency fields are rendered
- Deposit/Payment Plan and Expiration Date toggles are present
- Fee payer selection options are displayed
- Publish button is visible
- Auto-save status is shown
