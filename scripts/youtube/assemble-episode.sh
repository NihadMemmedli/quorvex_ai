#!/bin/bash
# Assemble a YouTube tutorial from a screen recording, ElevenLabs voiceover,
# and generated captions.

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
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

EPISODE_DIR="$PROJECT_ROOT/content/youtube/episodes/$EPISODE"
BUILD_DIR="$EPISODE_DIR/build"
VOICEOVER="$BUILD_DIR/voiceover-en.mp3"
CAPTIONS="$EPISODE_DIR/captions.srt"

if [[ -z "$OUTPUT" ]]; then
    OUTPUT="$BUILD_DIR/youtube-$EPISODE.mp4"
fi

if [[ -z "$RECORDING" ]]; then
    echo "Recording is required."
    echo "Usage: scripts/youtube/assemble-episode.sh --episode $EPISODE --recording path/to/recording.mp4"
    exit 1
fi

mkdir -p "$BUILD_DIR"

missing=0
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg not found. Install with: brew install ffmpeg"
    missing=1
fi
if ! command -v ffprobe >/dev/null 2>&1; then
    echo "ffprobe not found. Install with: brew install ffmpeg"
    missing=1
fi
if [[ ! -f "$RECORDING" ]]; then
    echo "Recording not found: $RECORDING"
    missing=1
fi
if [[ ! -f "$VOICEOVER" ]]; then
    echo "Voiceover not found: $VOICEOVER"
    echo "Run: make youtube-voice EP=$EPISODE"
    missing=1
fi
if [[ ! -f "$CAPTIONS" ]]; then
    echo "Captions not found: $CAPTIONS"
    echo "Run: make youtube-pack EP=$EPISODE"
    missing=1
fi
if [[ "$missing" -eq 1 ]]; then
    exit 1
fi

audio_duration=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$VOICEOVER" | cut -d'.' -f1)
target_duration=$((audio_duration + 2))
subtitle_style="FontName=Arial,FontSize=26,PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=44,Alignment=2"

echo "Assembling YouTube episode $EPISODE"
echo "  Recording: $RECORDING"
echo "  Voiceover: $VOICEOVER"
echo "  Captions:  $CAPTIONS"
echo "  Output:    $OUTPUT"

ffmpeg -y \
    -stream_loop -1 \
    -i "$RECORDING" \
    -i "$VOICEOVER" \
    -t "$target_duration" \
    -vf "subtitles=filename=${CAPTIONS}:force_style='${subtitle_style}',scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" \
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
    -map 0:v:0 \
    -map 1:a:0 \
    "$OUTPUT"

size_mb=$(du -m "$OUTPUT" | cut -f1)
echo "Saved $OUTPUT (${size_mb} MB)"
