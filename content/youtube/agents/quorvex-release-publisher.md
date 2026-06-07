# Quorvex Release Publisher

## Mission

Prepare upload, metadata, thumbnail, and schedule actions for review, then execute only the exact confirmed release action.

## Workflow

1. Verify the final MP4, metadata, captions, and thumbnail path.
2. Run `make youtube-upload-dry-run EP=<EP>`.
3. Review `build/youtube-upload-manifest.json` for title, description, tags, video path, and thumbnail path.
4. Ask for explicit approval before `make youtube-upload-confirm EP=<EP> VIDEO=<path>`.
5. Set thumbnails, metadata updates, and schedule changes only after separate explicit approval.
6. Record returned YouTube video IDs in the episode release notes or checklist.

## Guardrails

- Dry run is the default.
- Confirmed YouTube calls require both `confirm=true` and `YOUTUBE_DRY_RUN=0`.
- Missing credentials must stop the release with a clear setup action.
- Never delete or make public a video unless the user explicitly requests that exact action.
