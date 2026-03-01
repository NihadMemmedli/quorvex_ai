# Test Plan: Documentation Example Flow

## Application Overview

This test plan covers the Documentation Example Flow, which validates the user journey from example.com to the IANA example domains documentation page. The flow involves navigating to example.com, clicking the "Learn more" link, and verifying the redirect to the IANA documentation page.

**Key Selectors Discovered:**
- example.com heading: `getByRole('heading', { name: 'Example Domain', level: 1 })`
- Learn more link: `getByRole('link', { name: 'Learn more' })`
- IANA page heading: `getByRole('heading', { name: 'Example Domains', level: 1 })`
- IANA RFC 2606 link: `getByRole('link', { name: 'RFC 2606' })`
- IANA RFC 6761 link: `getByRole('link', { name: 'RFC 6761' })`

**Target URLs:**
- Start: https://example.com
- End: https://www.iana.org/help/example-domains

## Test Scenarios

### 1. Happy Path Tests

**Seed:** `tests/seed.spec.ts`

#### 1.1. Successful navigation from example.com to IANA documentation

**File:** `tests/generated/documentation-example-flow/happy-path/successful-navigation.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads successfully with title 'Example Domain'
    - expect: Main heading displays 'Example Domain'
    - expect: Informational paragraph about documentation use is visible
  2. Click the 'Learn more' link using getByRole('link', { name: 'Learn more' })
    - expect: Page navigates to IANA documentation page
    - expect: URL changes to https://www.iana.org/help/example-domains
    - expect: Page title changes to 'Example Domains'
  3. Verify the IANA page content
    - expect: Main heading displays 'Example Domains'
    - expect: RFC 2606 link is visible and clickable
    - expect: RFC 6761 link is visible and clickable
    - expect: Informational text about example domains is displayed

#### 1.2. Verify page structure and content on example.com

**File:** `tests/generated/documentation-example-flow/happy-path/page-structure.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads with correct title 'Example Domain'
    - expect: H1 heading with text 'Example Domain' is present
    - expect: Descriptive paragraph about domain purpose is visible
    - expect: Learn more link is present and clickable
  2. Verify the Learn more link properties
    - expect: Link has cursor: pointer styling
    - expect: Link href points to https://iana.org/domains/example
    - expect: Link is visible and enabled

#### 1.3. Verify IANA documentation page structure

**File:** `tests/generated/documentation-example-flow/happy-path/iana-page-structure.spec.ts`

**Steps:**
  1. Navigate to https://example.com and click 'Learn more' link
    - expect: Successfully navigates to IANA documentation page
  2. Verify page elements and structure
    - expect: H1 heading 'Example Domains' is present
    - expect: Navigation menu with Homepage, Domains, Protocols, Numbers, About links is visible
    - expect: RFC 2606 and RFC 6761 reference links are present
    - expect: Further Reading section with IANA-managed Reserved Domains link is visible
    - expect: Footer with copyright and additional links is present

#### 1.4. Verify RFC reference links on IANA page

**File:** `tests/generated/documentation-example-flow/happy-path/rfc-links.spec.ts`

**Steps:**
  1. Navigate to https://example.com and click 'Learn more' link
    - expect: Successfully navigates to IANA documentation page
  2. Click on RFC 2606 link using getByRole('link', { name: 'RFC 2606' })
    - expect: RFC 2606 page opens or navigates to /go/rfc2606
    - expect: Page loads without errors
  3. Navigate back to Example Domains page
    - expect: Successfully returns to Example Domains page
  4. Click on RFC 6761 link using getByRole('link', { name: 'RFC 6761' })
    - expect: RFC 6761 page opens or navigates to /go/rfc6761
    - expect: Page loads without errors

### 2. Edge Cases

**Seed:** `tests/seed.spec.ts`

#### 2.1. Direct navigation to IANA documentation page

**File:** `tests/generated/documentation-example-flow/edge-cases/direct-navigation.spec.ts`

**Steps:**
  1. Navigate directly to https://www.iana.org/help/example-domains
    - expect: Page loads successfully
    - expect: All page elements are rendered correctly
    - expect: No authentication or special access required

#### 2.2. Browser back button functionality

**File:** `tests/generated/documentation-example-flow/edge-cases/browser-back-button.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads successfully
  2. Click 'Learn more' link
    - expect: Navigates to IANA documentation page
  3. Use browser back button to navigate back
    - expect: Successfully returns to example.com
    - expect: Page content is correctly restored
    - expect: No 'Leave site?' dialog appears

#### 2.3. Multiple navigation cycles

**File:** `tests/generated/documentation-example-flow/edge-cases/multiple-navigation.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads successfully
  2. Click 'Learn more' link to go to IANA page
    - expect: Successfully navigates to IANA documentation
  3. Use browser back button to return to example.com
    - expect: Successfully returns to example.com
  4. Click 'Learn more' link again
    - expect: Successfully navigates to IANA documentation again
    - expect: No caching or state issues
  5. Repeat navigation cycle 3 more times
    - expect: All navigation cycles complete successfully
    - expect: No errors or unexpected behavior

### 3. Error Scenarios

**Seed:** `tests/seed.spec.ts`

#### 3.1. Handle slow network conditions

**File:** `tests/generated/documentation-example-flow/error-scenarios/slow-network.spec.ts`

**Steps:**
  1. Simulate slow network (3G) and navigate to https://example.com
    - expect: Page eventually loads within reasonable time
    - expect: Content is fully rendered
    - expect: No timeout errors occur
  2. Click 'Learn more' link under slow network conditions
    - expect: Navigation completes within reasonable time
    - expect: IANA page loads successfully
    - expect: No partial loading or missing content

#### 3.2. Verify graceful handling if IANA page is temporarily unavailable

**File:** `tests/generated/documentation-example-flow/error-scenarios/iana-unavailable.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads successfully
  2. Attempt to click 'Learn more' link when IANA is unavailable
    - expect: Appropriate error message or browser error page is shown
    - expect: No application crash or hang
    - expect: User can retry navigation

#### 3.3. Test navigation with JavaScript disabled

**File:** `tests/generated/documentation-example-flow/error-scenarios/no-javascript.spec.ts`

**Steps:**
  1. Disable JavaScript in browser and navigate to https://example.com
    - expect: Page still loads successfully
  2. Click 'Learn more' link with JavaScript disabled
    - expect: Navigation still works (these are static pages)
    - expect: IANA page loads correctly without JavaScript
    - expect: Content is fully accessible

#### 3.4. Handle invalid URL variations

**File:** `tests/generated/documentation-example-flow/error-scenarios/invalid-urls.spec.ts`

**Steps:**
  1. Navigate to https://example.com with trailing slash variations
    - expect: All URL variations load correctly
    - expect: No 404 or redirect errors occur
  2. Try http:// instead of https://
    - expect: Either page loads with redirect to HTTPS
    - expect: Or browser shows security warning
  3. Navigate to malformed IANA URLs
    - expect: Appropriate error handling
    - expect: 404 page or error message displayed

### 4. Accessibility

**Seed:** `tests/seed.spec.ts`

#### 4.1. Verify accessibility of example.com page

**File:** `tests/generated/documentation-example-flow/accessibility/example-com-accessibility.spec.ts`

**Steps:**
  1. Navigate to https://example.com
    - expect: Page loads successfully
  2. Check heading hierarchy and structure
    - expect: Only one H1 heading is present ('Example Domain')
    - expect: Heading levels follow proper hierarchy
    - expect: No skipped heading levels
  3. Verify link accessibility
    - expect: Learn more link has descriptive text
    - expect: Link is keyboard navigable
    - expect: Link has visible focus indicator
  4. Test keyboard navigation
    - expect: Tab key focuses on the Learn more link
    - expect: Enter/Return key activates the link
    - expect: All interactive elements are keyboard accessible

#### 4.2. Verify accessibility of IANA documentation page

**File:** `tests/generated/documentation-example-flow/accessibility/iana-accessibility.spec.ts`

**Steps:**
  1. Navigate to https://www.iana.org/help/example-domains
    - expect: Page loads successfully
  2. Check heading hierarchy and semantic structure
    - expect: H1 heading 'Example Domains' is present
    - expect: H2 heading 'Further Reading' is present
    - expect: Proper semantic HTML structure (main, article, nav) is used
  3. Verify all links have accessible names
    - expect: All navigation links have descriptive text
    - expect: RFC reference links have clear text
    - expect: Footer links are properly labeled
  4. Test keyboard navigation through page
    - expect: Tab key navigates through all interactive elements in logical order
    - expect: Focus indicator is visible on all focused elements
    - expect: Skip navigation links (if present) work correctly
