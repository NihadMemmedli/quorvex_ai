# Test Spec for Unique Localized Titles Across Pages

## Description
This test checks that all pages have unique localized titles, ensuring better user experience and SEO performance.

## Steps
1. Navigate to each route in AZ and EN locales.
2. Assert `document.title` is not equal to the generic 'mygov'.
3. Assert `document.title` contains a route-specific keyword.

## Expected Result
Each route returns a unique, localized, descriptive <title>.

## Pages to Test
- /
- /entities
- /contact-us
- /support
- /events
- /az/sitemap
- /document-serial-number
- /en
- /en/contact-us

## Notes
Make sure to check both Azerbaijani and English locales for each route.

## Evidence
Screenshots available for various pages checked.
