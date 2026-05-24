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
