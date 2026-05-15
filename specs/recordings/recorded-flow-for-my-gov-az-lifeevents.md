# Test: Recorded flow for my.gov.az/lifeEvents

## Description
Recorded from a Playwright codegen session and imported into Quorvex AI.

## Source
- Recorded at: 2026-05-15T19:16:22Z
- Target URL: https://my.gov.az/lifeEvents
- Raw Playwright code: `tests/recordings/recorded-flow-for-my-gov-az-lifeevents.spec.ts`

## Steps
1. Navigate to https://my.gov.az/lifeEvents
2. Click link named `Marriage AilÉ qurmaq`
3. Click text `AilÉ qurmaq, nikaha daxil`
4. Click link named `NikahÄ±n qeydiyyata alÄ±nmas`
5. Click element `#infoSection`
6. Click cell named `Bir nÉfÉr Ã¼Ã§Ã¼n tibbi mÃ¼ayinÉd`
7. Click button named `DAXÄ°L OLUN î©°`
8. Click button named `DigÉr Ã¼sullar`
9. Click text `SÄ°MA Ä°mza ilÉ SistemÉ daxil`

## Expected Outcome
- The recorded flow completes successfully without visible errors.

## Notes
The following recorded Playwright statements need review:
- `await page.getByRole('button', { name: 'MÜRACİƏT ET' }).first().click();`
- `await page.locator('path').first().click();`
