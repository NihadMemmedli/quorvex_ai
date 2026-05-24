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
#   ./scripts/demo-video/assemble-video.sh --recording /path/to/recording.webm
#   ./scripts/demo-video/assemble-video.sh --sound-design auto
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
RECORDING="$OUTPUT_DIR/recording.webm"
SOUND_DESIGN="auto"

# Parse arguments
LANG="both"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang)
            LANG="${2:-both}"
            shift 2
            ;;
        --recording)
            RECORDING="${2:-$RECORDING}"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="${2:-$OUTPUT_DIR}"
            shift 2
            ;;
        --sound-design)
            SOUND_DESIGN="${2:-$SOUND_DESIGN}"
            shift 2
            ;;
        en|az|both)
            LANG="$1"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

caption_path() {
    local lang="$1"
    local generated="$OUTPUT_DIR/captions-${lang}.srt"
    local legacy="$SCRIPT_DIR/captions-${lang}.srt"
    if [[ -f "$generated" ]]; then
        echo "$generated"
    else
        echo "$legacy"
    fi
}

sound_design_path() {
    local lang="$1"
    if [[ "$SOUND_DESIGN" == "none" || "$SOUND_DESIGN" == "off" ]]; then
        return 0
    fi
    if [[ "$SOUND_DESIGN" != "auto" ]]; then
        echo "$SOUND_DESIGN"
        return 0
    fi

    local generated="$OUTPUT_DIR/sound-design-${lang}.wav"
    if [[ -f "$generated" ]]; then
        echo "$generated"
    fi
}

# Verify prerequisites
check_prerequisites() {
    local missing=0

    if ! command -v ffmpeg &> /dev/null; then
        echo "❌ FFmpeg not found. Install with: brew install ffmpeg"
        missing=1
    fi

    if [[ ! -f "$RECORDING" ]]; then
        echo "❌ Recording not found: $RECORDING"
        echo "   Run the Playwright recording first: npx --yes tsx scripts/demo-video/record-demo.ts"
        missing=1
    fi

    if [[ "$LANG" == "en" || "$LANG" == "both" ]]; then
        if [[ ! -f "$OUTPUT_DIR/voiceover-en.mp3" ]]; then
            echo "❌ English voiceover not found: $OUTPUT_DIR/voiceover-en.mp3"
            echo "   Run: python scripts/demo-video/generate-voice.py --lang en"
            missing=1
        fi
        local captions_en
        captions_en="$(caption_path en)"
        if [[ ! -f "$captions_en" ]]; then
            echo "❌ English captions not found: $captions_en"
            missing=1
        fi
    fi

    if [[ "$LANG" == "az" || "$LANG" == "both" ]]; then
        if [[ ! -f "$OUTPUT_DIR/voiceover-az.mp3" ]]; then
            echo "❌ Azeri voiceover not found: $OUTPUT_DIR/voiceover-az.mp3"
            echo "   Run: python scripts/demo-video/generate-voice.py --lang az"
            missing=1
        fi
        local captions_az
        captions_az="$(caption_path az)"
        if [[ ! -f "$captions_az" ]]; then
            echo "❌ Azeri captions not found: $captions_az"
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
    local captions
    captions="$(caption_path "$lang")"
    local sound_design
    sound_design="$(sound_design_path "$lang")"
    local output="$OUTPUT_DIR/demo-${lang}.mp4"
    local lang_label
    lang_label="$(printf '%s' "$lang" | tr '[:lower:]' '[:upper:]')"

    echo ""
    echo "🎬 Assembling ${lang_label} video..."
    echo "   Recording: $RECORDING"
    echo "   Voiceover: $voiceover"
    echo "   Captions:  $captions"
    if [[ -n "$sound_design" ]]; then
        echo "   Sound FX:  $sound_design"
    fi
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

    if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles "; then
        echo "   FFmpeg subtitles filter unavailable; using PNG caption overlays."
        overlay_args=(
            "$SCRIPT_DIR/assemble-with-overlays.py"
            --recording "$RECORDING" \
            --voiceover "$voiceover" \
            --captions "$captions" \
            --output "$output" \
            --overlay-dir "$OUTPUT_DIR/caption-overlays"
        )
        if [[ -n "$sound_design" ]]; then
            overlay_args+=(--sound-design "$sound_design")
        fi
        python "${overlay_args[@]}"

        local size_mb
        size_mb=$(du -m "$output" | cut -f1)
        echo "   ✅ Saved: $output (${size_mb} MB)"
        if [[ $size_mb -gt 200 ]]; then
            echo "   ⚠️  File exceeds LinkedIn's 200MB limit. Consider reducing quality."
        fi
        return
    fi

    if [[ -n "$sound_design" ]]; then
        ffmpeg -y \
            -stream_loop -1 \
            -i "$RECORDING" \
            -i "$voiceover" \
            -i "$sound_design" \
            -t "$target_duration" \
            -filter_complex "[0:v]subtitles=filename=${captions}:force_style='${subtitle_style}',scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black[v];[1:a]volume=1.0[a0];[2:a]volume=0.32[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]" \
            -map "[v]" \
            -map "[a]" \
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
            "$output" 2>/dev/null
    else
        ffmpeg -y \
            -stream_loop -1 \
            -i "$RECORDING" \
            -i "$voiceover" \
            -t "$target_duration" \
            -vf "subtitles=filename=${captions}:force_style='${subtitle_style}',scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black" \
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
    fi

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
