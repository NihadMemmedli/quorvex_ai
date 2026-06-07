# Test: Create Request opens the Business Payment Request Builder

## Source
Generated from: `verify-create-link-triggers-trip-creation-flow.md`
Test ID: TC-005
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
** Verify that clicking "Create Request" on the creation hub page opens the Business Payment Request builder form with all expected fields.

## Preconditions
- **
- User is logged in
- User is on the creation hub page (`/itinerary_builder/create`)

## Steps

1. Click the "Create Request" link: `getByRole('link', { name: 'Create Request' })`
2. Verify the URL changes to `/payment_request/{id}/builder`
3. Verify the "Title" textbox is present with placeholder "e.g. Epic Japan Trip Payment Request"
4. Verify the "Request ID" textbox is present with placeholder "e.g. ZXN-121"
5. Verify the "Due Date" field is present with calendar picker
6. Verify the "Amount" textbox is present
7. Verify the currency dropdown is present with "USD" selected
8. Verify the "Upload a document" section with "Upload Document" button
9. Verify the "Reference" textbox is present with placeholder "Write the purpose of your request here..."
10. Verify the "Who pays the fees?" section with Organizer/Payer options
11. Verify the "Link a trip (optional)" search field is present
12. Verify the "Create Request" submit button is present: `getByRole('button', { name: 'Create Request' })`

## Expected Outcome

- The Business Payment Request builder opens with all form fields
- Title, Request ID, Due Date, Amount, Currency fields are rendered
- Document upload section (PDF, up to 20MB) is present
- Reference text area is present
- Fee payer selection with Organizer/Payer options is displayed
- Trip linking search is available
- Create Request submit button is visible
