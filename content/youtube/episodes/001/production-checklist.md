# Production Checklist

## Before Recording

- Run `make youtube-demo-seed`.
- If Postgres is not running, use `make youtube-demo-seed SKIP_DATABASE=1` and skip the database-testing shot.
- Start the app and open the dashboard.
- Select `Quorvex Demo Shop` in the project selector.
- Open the failed checkout run before recording starts so the first frame is a red run, not the dashboard overview.
- Confirm the first 5 seconds can show the red failed checkout status and the selector drift log evidence.
- Confirm dashboard shows failed runs, flaky tests, slowest tests, and failure categories.
- Confirm `/runs` lists seeded checkout runs.
- Confirm the selector drift run detail opens and shows logs.
- Confirm `/agents` lists `Checkout Failure Triage`.
- Confirm agent findings, test ideas, and evidence tabs have content.
- Confirm `/specs` shows the `quorvex-demo-shop` specs.
- Confirm `/database-testing` shows `Quorvex Demo Shop` data if database seed was enabled.

## Browser Setup

- Use a clean browser profile.
- Set zoom to 100 percent.
- Use a 1440x900 or 1920x1080 capture area.
- Hide bookmarks and unrelated extensions.
- Keep the terminal out of frame unless showing the seed command.

## Delivery Notes

- Keep the tone practical and QA-focused.
- Avoid implying the agent fixes code automatically.
- Distinguish product defects from automation maintenance.
- Keep the platform tour narrow: dashboard, runs, agents, specs, database testing.
- Strongest on-screen moments: red checkout failure, hidden Pay now locator drift, Payment authorized after expired card, cart total mismatch, flaky refresh timeout, agent findings, API-backed cart total test idea, database payment/order mismatch.

## Final Commands

- `make youtube-demo-seed`
- `make youtube-voice EP=001 VOICE=DODLEQrClDo8wCz460ld`
- `make youtube-final EP=001 RECORDING=path/to/recording.mp4`

## Final QA

- Rewatch the first 5 seconds and confirm the hook shows a red checkout failure immediately.
- Confirm the first 30 seconds does not feel like a dashboard overview.
- Confirm no private environment variables, tokens, or local customer data are visible.
- Confirm the pinned comment includes the seed command.
