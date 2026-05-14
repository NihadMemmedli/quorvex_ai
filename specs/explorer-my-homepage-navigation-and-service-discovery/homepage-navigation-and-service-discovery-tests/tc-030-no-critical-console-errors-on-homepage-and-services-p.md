# Test: No Critical Console Errors on Homepage and Services Page Load

## Source
Generated from: `homepage-navigation-and-service-discovery.md`
Test ID: TC-030
Category: Scope

## Summary Table
| Test ID | Description | Priority | Type |
|---------|-------------|----------|------|
| TC-001 | Homepage loads within 5 seconds | High | Performance |
| TC-002 | Homepage hero/banner visible | High | Functional |
| TC-003 | Navigation menu with top-level links | High | Functional |
| TC-004 | Featured services count > 0 | High | Functional |
| TC-005 | "All Services" link visible on homepage | High | Functional |
| TC-006 | "All Services" click navigates to /az/services | High | Functional |
| TC-007 | Services catalog shows categories | High | Functional |
| TC-008 | Category filter updates services list | High | Functional |
| TC-009 | Services catalog count > 0 | High | Functional |
| TC-010 | Service card shows required info | Medium | Functional |
| TC-011 | Language toggle visible on homepage | High | Functional |
| TC-012 | Language switch AZ to RU | High | Functional |
| TC-013 | Language switch AZ to EN | Medium | Functional |
| TC-014 | Language persists homepage to services | High | Functional |
| TC-015 | Language toggle on services page stays on services | Medium | Functional |
| TC-016 | Search filter on services page | Medium | Functional |
| TC-017 | Empty state on no-results filter | Medium | Edge Case |
| TC-018 | No indefinite spinner on API error | Medium | Error Handling |
| TC-019 | Breadcrumb navigation on services page | Low | Functional |
| TC-020 | Back navigation from services to homepage | Medium | Functional |
| TC-021 | Featured service card to service detail | High | Functional |
| TC-022 | Footer present with links | Low | Functional |
| TC-023 | Responsive design on mobile viewport | Medium | Responsive |
| TC-024 | Proper heading structure (accessibility) | Medium | Accessibility |
| TC-025 | Interactive elements have accessible labels | Medium | Accessibility |
| TC-026 | Direct URL navigation to /az/services | Medium | Functional |
| TC-027 | Invalid URL shows 404 or redirect | Low | Error Handling |
| TC-028 | Multiple category selection behavior | Medium | Edge Case |
| TC-029 | Scroll position after back navigation | Low | UX |
| TC-030 | No critical console errors on page load | High | Quality |

## Notes and Assumptions
1. The portal operates in Azerbaijani (AZ) by default when no language is set; additional languages are Russian (RU) and English (EN).
2. The "All Services" button text is expected to be "Butun xidmetler" in Azerbaijani; testers should adapt selectors to the active language at runtime.
3. The services catalog URL is assumed to be https://my.gov.az/az/services with the "az" language prefix; this prefix changes with language switching to /ru/services or /en/services.
4. Category filters may use either buttons with active/selected CSS states or radio-style inputs.
5. TC-017 and TC-018 (edge cases) may require simulated API errors or data manipulation; coordinate with the development team if these cannot be triggered in the live environment.
6. TC-023 (mobile responsive) should also be validated on actual mobile devices in addition to emulated viewports.
7. The featured services section on the homepage may be driven by a CMS or API; the count of services is expected to be > 0 in any valid production or staging environment.
8. No authentication is required to browse the homepage or services catalog; these are public-facing pages.

## Description
Verify that the homepage and services catalog page load without any critical JavaScript errors in the browser console.

## Preconditions
- Fresh browser session with console monitoring enabled.

## Steps

1. Open a new browser window with console monitoring enabled.
2. Navigate to https://my.gov.az/.
3. Wait for the page to fully load (wait for network idle).
4. Check the browser console for errors using `browser_console_messages`.
5. Verify there are no errors of severity "error" (critical JS errors, failed critical resource loads).
6. Note any warnings for documentation but do not fail on warnings alone.
7. Navigate to https://my.gov.az/az/services.
8. Repeat the console check on the services page.
