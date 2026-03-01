#!/bin/bash
# ============================================================
# Video Assembly Pipeline
# Combines Playwright recording + AI voiceover + burned-in captions
# into LinkedIn-optimized MP4 videos (English + Azeri).
#
# Usage:
#   ./scripts/demo-video/assemble-video.sh
#   ./scripts/demo-video/assemble-video.sh --lang en   # English only
#   ./scripts/demo-video/assemble-video.sh --lang az   # Azeri only
#
# Prerequisites:
#   - FFmpeg installed (brew install ffmpeg)
#   - Recording at output/recording.webm
#   - Voiceovers at output/voiceover-{en,az}.mp3
#   - Captions at captions-{en,az}.srt
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
CAPTIONS_EN="$SCRIPT_DIR/captions-en.srt"
CAPTIONS_AZ="$SCRIPT_DIR/captions-az.srt"
RECORDING="$OUTPUT_DIR/recording.webm"

# Parse arguments
LANG="${1:-both}"
if [[ "$LANG" == "--lang" ]]; then
    LANG="${2:-both}"
fi

# Verify prerequisites
check_prerequisites() {
    local missing=0

    if ! command -v ffmpeg &> /dev/null; then
        echo "❌ FFmpeg not found. Install with: brew install ffmpeg"
        missing=1
    fi

    if [[ ! -f "$RECORDING" ]]; then
        echo "❌ Recording not found: $RECORDING"
        echo "   Run the Playwright recording first: npx tsx scripts/demo-video/record-demo.ts"
        missing=1
    fi

    if [[ "$LANG" == "en" || "$LANG" == "both" ]]; then
        if [[ ! -f "$OUTPUT_DIR/voiceover-en.mp3" ]]; then
            echo "❌ English voiceover not found: $OUTPUT_DIR/voiceover-en.mp3"
            echo "   Run: python scripts/demo-video/generate-voice.py --lang en"
            missing=1
        fi
        if [[ ! -f "$CAPTIONS_EN" ]]; then
            echo "❌ English captions not found: $CAPTIONS_EN"
            missing=1
        fi
    fi

    if [[ "$LANG" == "az" || "$LANG" == "both" ]]; then
        if [[ ! -f "$OUTPUT_DIR/voiceover-az.mp3" ]]; then
            echo "❌ Azeri voiceover not found: $OUTPUT_DIR/voiceover-az.mp3"
            echo "   Run: python scripts/demo-video/generate-voice.py --lang az"
            missing=1
        fi
        if [[ ! -f "$CAPTIONS_AZ" ]]; then
            echo "❌ Azeri captions not found: $CAPTIONS_AZ"
            missing=1
        fi
    fi

    if [[ $missing -eq 1 ]]; then
        echo ""
        echo "Fix the above issues and try again."
        exit 1
    fi
}

# Assemble a single video
assemble_video() {
    local lang="$1"
    local voiceover="$OUTPUT_DIR/voiceover-${lang}.mp3"
    local captions="$SCRIPT_DIR/captions-${lang}.srt"
    local output="$OUTPUT_DIR/demo-${lang}.mp4"

    echo ""
    echo "🎬 Assembling ${lang^^} video..."
    echo "   Recording: $RECORDING"
    echo "   Voiceover: $voiceover"
    echo "   Captions:  $captions"
    echo "   Output:    $output"

    # Get voiceover duration to trim/loop video to match
    local audio_duration
    audio_duration=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$voiceover" | cut -d'.' -f1)
    # Add 2 seconds of padding at the end
    local target_duration=$((audio_duration + 2))
    echo "   Audio duration: ${audio_duration}s → Video target: ${target_duration}s"

    # Caption style: white text on dark semi-transparent background
    # Font size 24, centered at bottom, with margin
    local subtitle_style="FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=40,Alignment=2"

    ffmpeg -y \
        -i "$RECORDING" \
        -i "$voiceover" \
        -t "$target_duration" \
        -vf "subtitles=${captions}:force_style='${subtitle_style}',scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" \
        -c:v libx264 \
        -preset medium \
        -crf 23 \
        -profile:v high \
        -level 4.0 \
        -pix_fmt yuv420p \
        -c:a aac \
        -b:a 128k \
        -ar 44100 \
        -r 30 \
        -movflags +faststart \
        -map 0:v:0 \
        -map 1:a:0 \
        "$output" 2>/dev/null

    local size_mb
    size_mb=$(du -m "$output" | cut -f1)
    echo "   ✅ Saved: $output (${size_mb} MB)"

    # Warn if over LinkedIn's limit
    if [[ $size_mb -gt 200 ]]; then
        echo "   ⚠️  File exceeds LinkedIn's 200MB limit. Consider reducing quality."
    fi
}

# Main
echo "🎥 Video Assembly Pipeline"
echo "=========================="

check_prerequisites

if [[ "$LANG" == "en" || "$LANG" == "both" ]]; then
    assemble_video "en"
fi

if [[ "$LANG" == "az" || "$LANG" == "both" ]]; then
    assemble_video "az"
fi

echo ""
echo "✅ Assembly complete!"
echo ""
echo "Output files:"
if [[ "$LANG" == "en" || "$LANG" == "both" ]]; then
    echo "  📹 $OUTPUT_DIR/demo-en.mp4"
fi
if [[ "$LANG" == "az" || "$LANG" == "both" ]]; then
    echo "  📹 $OUTPUT_DIR/demo-az.mp4"
fi
echo ""
echo "Next steps:"
echo "  1. Preview the video(s) locally"
echo "  2. Upload to LinkedIn"
echo "  3. Add caption text and hashtags:"
echo "     #TestAutomation #Playwright #AI #DevTools #QA #SoftwareTesting"
