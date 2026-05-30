# Test: Recorded flow for my.gov.az/serviceCategories

## Description
Recorded from a Playwright codegen session and imported into Quorvex AI.

## Source
- Recorded at: 2026-05-29T18:37:22Z
- Target URL: https://my.gov.az/serviceCategories
- Raw Playwright code: `tests/recordings/recorded-flow-for-my-gov-az-servicecategories.spec.ts`

## Steps
1. Navigate to https://my.gov.az/serviceCategories
2. Click button named `Bağla`
3. Click button named `Daxil ol`
4. Navigate to https://mygovid.gov.az/auth
5. Click button named `Digər üsullar`
6. Click text `İdentifikasiya nömrəsi ilə`
7. Click textbox named `İdentifikasiya nömrəsi`
8. Enter `1xck201` into textbox named `İdentifikasiya nömrəsi`
9. Press Tab in textbox named `İdentifikasiya nömrəsi`
10. Enter `Generation77!!` into textbox named `Şifrə`
11. Press Alt+a in textbox named `Şifrə`
12. Press Alt+a in textbox named `Şifrə`
13. Double-click textbox named `Şifrə`
14. Enter `Jj3630882!!!` into textbox named `Şifrə`
15. Navigate to https://my.gov.az/serviceCategories
16. Click tab named `Qurumlar`
17. Click text `Dövlət Gömrük Komitəsi(10)10`
18. Click link named `Mərkəzi Seçki Komissiyası Mə`
19. Click link named `Onlayn müraciət`

## Expected Outcome
- The recorded flow completes successfully without visible errors.

## Notes
The following recorded Playwright statements need review:
- `await page.routeFromHAR('/app/runs/recordings/recording_20260529_183357_1c8a1f6d/recording.har');`
- `await page.locator('div').filter({ hasText: /^Daxil ol$/ }).click();`
- `await page.getByRole('button', { name: 'MÜRACİƏT ET' }).first().click();`
- `await page.getByRole('button').nth(4).click();`
