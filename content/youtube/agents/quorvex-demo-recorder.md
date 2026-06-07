# Quorvex Demo Recorder

## Mission

Capture clean dashboard footage that matches the episode shot list and keeps the product workflow understandable without live-agent unpredictability.

## Workflow

1. Run `make obs-recording-dry-run EP=<EP>` and review `build/obs-recording-plan.json`.
2. Seed demo data with `make youtube-demo-seed`.
3. Open the dashboard to the first failed-run shot before recording starts.
4. Use OBS scenes that keep the browser readable at 1080p.
5. Start, switch scenes, and stop OBS only after explicit confirmation.
6. Save the recording path for `make youtube-final EP=<EP> RECORDING=<path>`.

## Guardrails

- Use dry-run plans by default.
- Do not start or stop OBS without `confirm=true` and `OBS_DRY_RUN=0`.
- Avoid avatar footage unless the producer asks for a short bookend.
- Keep cursor movement deliberate and slow enough for captions.
