# Quorvex Agent Operating Notes

## Company Network Deployment Handoff

- Before continuing company-network deployment work, read `deploy/company-network-handoff.md`.
- Treat company deployment as external-nginx mode: company DNS/TLS/nginx proxies the Compose app; do not enable or depend on the repo-managed nginx container unless explicitly asked.
- Never publish real secrets into tracked files. Use `.env.prod`, `.env`, `.env.local`, `.secrets/`, or shell environment variables for deployment credentials.

## YouTube Producer Workflow

- Keep episode artifacts under `content/youtube/episodes/<EP>/`. Generated media, upload manifests, and OBS plans belong under `content/youtube/episodes/<EP>/build/`.
- Use the configured MCP servers for production work when available: GitHub, Playwright, ElevenLabs, Descript, Canva, HeyGen, vidIQ, `youtube-upload`, and `obs`.
- Treat the episode pack as source of truth: `brief.md`, `script.md`, `captions.srt`, `metadata.md`, `shot-list.md`, `avatar-segments.md`, and `production-checklist.md`.
- Prefer dashboard footage over avatar footage. Avatar footage should be short bookends or transitions only.
- Never publish, schedule, delete, upload, set thumbnails, or mutate YouTube metadata without explicit user approval for that exact action.
- Default public, costly, or account-mutating actions to dry-run manifests. YouTube actions require `confirm=true` and `YOUTUBE_DRY_RUN=0`; OBS recording control requires `confirm=true` and `OBS_DRY_RUN=0`.
- Keep secrets out of Git. Use `.secrets/`, `.env`, `.env.local`, or shell environment variables for OAuth tokens, OBS passwords, and API keys.
- Before final upload, verify the dashboard route with Playwright, prepare an OBS recording plan, assemble the final MP4, prepare the YouTube upload dry run, and ask for explicit approval before confirmed upload or scheduling.
