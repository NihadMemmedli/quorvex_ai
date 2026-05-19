# Test: random test name

## Description
Recorded from a Playwright codegen session and imported into Quorvex AI.

## Source
- Recorded at: 2026-05-18T14:44:58Z
- Target URL: https://my.gov.az/
- Raw Playwright code: `tests/recordings/random-test-name.spec.ts`

## Steps
1. Navigate to https://my.gov.az/
2. Click button named `Daxil ol`
3. Click button named `DigÉr Ã¼sullar`
4. Click text `Geri`

## Expected Outcome
- The recorded flow completes successfully without visible errors.

## Notes
The following recorded Playwright statements need review:
- `await page.routeFromHAR('/app/runs/recordings/recording_20260518_144353_6c3141aa/recording.har');`
- `await page.locator('.panel-left').first().click();`
- `await page.locator('div').filter({ hasText: /^EN$/ }).click();`
