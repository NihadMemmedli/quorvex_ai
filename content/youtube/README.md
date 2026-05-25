# Quorvex AI YouTube Channel

This workspace keeps the YouTube tutorial process repeatable: episode briefs,
scripts, avatar prompts, voiceover inputs, captions, upload metadata, and
production checklists live together.

## Launch Format

- Language: English first.
- Presenter: AI avatar for hooks, transitions, and outros.
- Main footage: real Quorvex screen recordings, terminal commands, generated
  Playwright code, and dashboard evidence.
- Voice: ElevenLabs narration from the generated script.
- Budget posture: use avatar minutes sparingly and put most runtime into
  screen-first teaching.

## Generate an Episode Pack

```bash
make youtube-pack EP=001
```

The generated pack is written to:

```text
content/youtube/episodes/001/
```

Useful files:

- `script.md` - narration script for ElevenLabs.
- `avatar-segments.md` - short avatar lines for HeyGen, Synthesia, or another
  digital presenter tool.
- `captions.srt` - draft captions for the narration.
- `metadata.md` - title, description, tags, pinned comment, and chapters.
- `shot-list.md` - screen recording plan.
- `production-checklist.md` - publish readiness checklist.

## Generate Voiceover

After creating the pack, generate narration with the existing ElevenLabs helper:

```bash
python scripts/demo-video/generate-voice.py \
  --lang en \
  --input content/youtube/episodes/001/script.md \
  --output-dir content/youtube/episodes/001/build
```

Generated media under `content/youtube/episodes/*/build/` is local-only and
ignored by Git.

## Assemble a YouTube MP4

After recording the product walkthrough and generating narration:

```bash
make youtube-assemble EP=001 RECORDING=path/to/screen-recording.mp4
```

This exports:

```text
content/youtube/episodes/001/build/youtube-001.mp4
```

Avatar clips should be edited into the screen recording before assembly, or
assembled in a video editor after this export. Keep avatar segments short so the
main tutorial remains product-led.

## Avatar Use

Use avatar clips for:

- Opening hook.
- Section transitions.
- Final recap and call to action.

Do not make the whole tutorial a talking-avatar video. Developer trust comes
from showing the product, the terminal, generated code, and run artifacts.

When uploading, disclose realistic AI avatar usage if YouTube asks for altered
or synthetic content disclosure. Voice-only cleanup or cloning your own voice
for narration generally does not need the same disclosure, but avatar-led clips
should be treated conservatively.

## Generate Avatar Payloads

Set the HeyGen IDs after creating or choosing a reusable avatar look and voice:

```bash
export HEYGEN_AVATAR_ID=your_look_id
export HEYGEN_VOICE_ID=your_voice_id
```

Generate JSON payloads for the short presenter clips:

```bash
make youtube-avatar EP=001
```

This writes payloads under:

```text
content/youtube/episodes/001/build/avatar/
```

To submit them to HeyGen through the API, also set `HEYGEN_API_KEY` and pass:

```bash
make youtube-avatar EP=001 SUBMIT=1
```

Submitting may spend HeyGen API balance. Use this only after reviewing
`avatar-segments.md`.

## First Season

The first eight episode briefs live in `episode-catalog.json`. Start with
episode `001`, publish it, then use analytics and comments to adjust the next
two scripts before scaling production.
