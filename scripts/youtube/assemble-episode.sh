#!/bin/bash
# Assemble a YouTube tutorial from screen recording, voiceover, and captions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

EPISODE="001"
RECORDING=""
OUTPUT=""
CRF="${YOUTUBE_CRF:-21}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --episode)
            EPISODE="${2:-$EPISODE}"
            shift 2
            ;;
        --recording)
            RECORDING="${2:-}"
            shift 2
            ;;
        --output)
            OUTPUT="${2:-}"
            shift 2
            ;;
        --crf)
            CRF="${2:-$CRF}"
            shift 2
            ;;
        --help|-h)
            cat <<USAGE
Usage: scripts/youtube/assemble-episode.sh --episode 001 --recording path/to/recording.mp4

Options:
  --episode ID       Episode id (default: 001)
  --recording FILE   Screen recording to combine with narration
  --output FILE      Final MP4 path (default: content/youtube/episodes/<id>/build/youtube-<id>.mp4)
  --crf VALUE        x264 quality value, lower is higher quality (default: $CRF)
USAGE
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

EPISODE_DIR="$PROJECT_ROOT/content/youtube/episodes/$EPISODE"
BUILD_DIR="$EPISODE_DIR/build"
VOICEOVER="$BUILD_DIR/voiceover-en.mp3"
CAPTIONS="$EPISODE_DIR/captions.srt"
OVERLAY_DIR="$BUILD_DIR/caption-overlays"

if [[ -z "$OUTPUT" ]]; then
    OUTPUT="$BUILD_DIR/youtube-$EPISODE.mp4"
fi

if [[ -z "$RECORDING" ]]; then
    echo "Error: RECORDING is required." >&2
    echo "Usage: make youtube-assemble EP=$EPISODE RECORDING=path/to/recording.mp4" >&2
    exit 1
fi

missing=0
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Error: ffmpeg not found. Install it with: brew install ffmpeg" >&2
    missing=1
fi
if ! command -v ffprobe >/dev/null 2>&1; then
    echo "Error: ffprobe not found. Install it with: brew install ffmpeg" >&2
    missing=1
fi
if [[ ! -f "$RECORDING" ]]; then
    echo "Error: recording not found: $RECORDING" >&2
    missing=1
fi
if [[ ! -f "$VOICEOVER" ]]; then
    echo "Error: voiceover not found: $VOICEOVER" >&2
    echo "Run: make youtube-voice EP=$EPISODE VOICE=${ELEVENLABS_DEMO_VOICE_ID:-DODLEQrClDo8wCz460ld}" >&2
    missing=1
fi
if [[ ! -f "$CAPTIONS" ]]; then
    echo "Error: captions not found: $CAPTIONS" >&2
    echo "Expected episode captions at content/youtube/episodes/$EPISODE/captions.srt" >&2
    missing=1
fi
if [[ "$missing" -eq 1 ]]; then
    exit 1
fi

mkdir -p "$BUILD_DIR"

audio_duration="$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$VOICEOVER")"
target_duration="$(python - "$audio_duration" <<'PY'
import sys
print(int(float(sys.argv[1])) + 2)
PY
)"
subtitle_style="FontName=Arial,FontSize=26,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=44,Alignment=2"

echo "Assembling YouTube episode $EPISODE"
echo "  Recording: $RECORDING"
echo "  Voiceover: $VOICEOVER"
echo "  Captions:  $CAPTIONS"
echo "  Output:    $OUTPUT"

set +e
ffmpeg -y \
    -stream_loop -1 \
    -i "$RECORDING" \
    -i "$VOICEOVER" \
    -t "$target_duration" \
    -vf "subtitles=filename='${CAPTIONS}':force_style='${subtitle_style}',scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" \
    -map 0:v:0 \
    -map 1:a:0 \
    -c:v libx264 \
    -preset medium \
    -crf "$CRF" \
    -profile:v high \
    -level 4.1 \
    -pix_fmt yuv420p \
    -c:a aac \
    -b:a 192k \
    -ar 48000 \
    -r 30 \
    -movflags +faststart \
    "$OUTPUT"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
    echo "FFmpeg subtitle filter failed; retrying with rendered PNG caption overlays." >&2
    python "$PROJECT_ROOT/scripts/demo-video/assemble-with-overlays.py" \
        --recording "$RECORDING" \
        --voiceover "$VOICEOVER" \
        --captions "$CAPTIONS" \
        --output "$OUTPUT" \
        --overlay-dir "$OVERLAY_DIR"
fi

size_mb=$(du -m "$OUTPUT" | cut -f1)
echo "Saved $OUTPUT (${size_mb} MB)"
