# Demo Video Pipeline

This folder creates GitHub and LinkedIn-ready demo videos from repo positioning, dashboard recordings, AI narration, generated voiceover, and burned-in captions.

## Setup

```bash
python -m pip install -r scripts/demo-video/requirements.txt
brew install ffmpeg
export OPENAI_API_KEY=...
export ELEVENLABS_API_KEY=...
```

The dashboard should be running before recording:

```bash
make dev
```

## Full Pipeline

```bash
./scripts/demo-video/create-video.sh --lang en --base-url http://localhost:3000
```

Premium LinkedIn/storytelling cut with visible cursor movement, human-paced
scrolling, a typed assistant moment, ElevenLabs narration, captions, and subtle
UI sound design:

```bash
./scripts/demo-video/create-video.sh --premium --lang en --base-url http://localhost:3000 --duration 85
```

Use an existing dashboard capture instead of recording again:

```bash
./scripts/demo-video/create-video.sh --premium --lang en --recording scripts/demo-video/output/recording-ui.mp4 --skip-recording
```

Outputs are written to `scripts/demo-video/output/`:

- `narration-en.md`
- `captions-en.srt`
- `linkedin-post-en.md`
- `github-caption-en.txt`
- `recording.webm`
- `voiceover-en.mp3`
- `sound-design-en.wav`
- `demo-en.mp4`

## Individual Steps

Generate script, captions, and social copy:

```bash
python scripts/demo-video/generate-script.py --lang en
```

Generate deterministic local content without OpenAI:

```bash
python scripts/demo-video/generate-script.py --lang en --dry-run
```

Record the dashboard:

```bash
npx --yes tsx scripts/demo-video/record-demo.ts --base-url http://localhost:3000 --output-dir scripts/demo-video/output
```

Record the premium dashboard walkthrough:

```bash
npx --yes tsx scripts/demo-video/record-demo.ts --mode premium --base-url http://localhost:3000 --output-dir scripts/demo-video/output
```

Generate voiceover from the generated narration:

```bash
python scripts/demo-video/generate-voice.py --lang en
```

Generate subtle UI sound design:

```bash
python scripts/demo-video/generate-sound-design.py --lang en
```

Assemble the final MP4:

```bash
./scripts/demo-video/assemble-video.sh --lang en
```

Assemble with sound design:

```bash
./scripts/demo-video/assemble-video.sh --lang en --sound-design auto
```

Use `--lang az` or `--lang both` for Azerbaijani output.

## YouTube Tutorial Workflow

The short demo pipeline above remains focused on GitHub, LinkedIn, and launch
assets. Long-form YouTube tutorials use the separate content workspace in
`content/youtube/`.

Generate an episode production pack:

```bash
make youtube-pack EP=001
```

Generate ElevenLabs narration for that episode:

```bash
make youtube-voice EP=001
```

Assemble a 1080p YouTube MP4 from a product screen recording:

```bash
make youtube-assemble EP=001 RECORDING=path/to/screen-recording.mp4
```

The episode pack includes:

- `script.md` for narration
- `avatar-segments.md` for short AI-avatar clips
- `captions.srt` for draft captions
- `metadata.md` for title, description, tags, chapters, and pinned comment
- `shot-list.md` for product footage
- `production-checklist.md` for publish readiness

Avatar clips should be used for hooks, transitions, and outros while the main
runtime stays focused on real Quorvex screen footage, terminal output, generated
Playwright code, and run artifacts.
