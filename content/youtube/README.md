# Quorvex AI YouTube Production

This folder contains deterministic production assets for Quorvex AI product videos.

Episode 001 is designed to be recorded against the seeded `Quorvex Demo Shop` project:

```bash
make youtube-demo-seed
```

Use `SKIP_DATABASE=1` when the local database-testing schema is not needed:

```bash
make youtube-demo-seed SKIP_DATABASE=1
```

Generate narration with the default ElevenLabs DODLE voice ID:

```bash
make youtube-voice EP=001 VOICE=DODLEQrClDo8wCz460ld
```

Generate a short preview before full narration:

```bash
ELEVENLABS_DEMO_VOICE_ID=DODLEQrClDo8wCz460ld \
  venv/bin/python scripts/demo-video/generate-voice.py \
  --lang en \
  --input /tmp/quorvex-voice-preview.md \
  --output-dir content/youtube/episodes/001/build/voice-preview-dodle
```

To use a different ElevenLabs account voice, list voices and set the exact ID:

```bash
python scripts/demo-video/generate-voice.py --list-voices
export ELEVENLABS_DEMO_VOICE_ID=...
```

Assemble the final MP4 from a real screen recording:

```bash
make youtube-final EP=001 RECORDING=path/to/recording.mp4
```

The final export is written to `content/youtube/episodes/001/build/youtube-001.mp4`. Generated media under `build/` is local-only and ignored by Git.

Prepare MCP-controlled release dry runs:

```bash
make youtube-mcp-check EP=001
make obs-recording-dry-run EP=001
make youtube-upload-dry-run EP=001
```

Confirmed actions are intentionally separate:

```bash
make obs-recording-confirm EP=001
make youtube-upload-confirm EP=001 VIDEO=content/youtube/episodes/001/build/youtube-001.mp4
```

Confirmed YouTube actions require `YOUTUBE_DRY_RUN=0` and explicit confirmation in the tool call. Confirmed OBS actions require `OBS_DRY_RUN=0` and explicit confirmation.
