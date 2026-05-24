#!/bin/bash
# End-to-end demo video pipeline:
# script/captions -> screen recording -> ElevenLabs voice -> MP4 assembly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ -z "${PYTHON_BIN:-}" && -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON_BIN:-python}"
fi

LANG="en"
BASE_URL="${DEMO_BASE_URL:-http://localhost:3000}"
OUTPUT_DIR="$SCRIPT_DIR/output"
RECORDING=""
VOICE="${ELEVENLABS_DEMO_VOICE:-auto}"
MODEL="${OPENAI_MODEL:-gpt-5.4-mini}"
DURATION=""
DRY_RUN_SCRIPT=0
SKIP_SCRIPT=0
SKIP_SEED=0
SKIP_RECORDING=0
SKIP_VOICE=0
SKIP_SOUND_DESIGN=0
PREMIUM=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lang)
            LANG="${2:-$LANG}"
            shift 2
            ;;
        --base-url)
            BASE_URL="${2:-$BASE_URL}"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="${2:-$OUTPUT_DIR}"
            shift 2
            ;;
        --recording)
            RECORDING="${2:-}"
            SKIP_RECORDING=1
            shift 2
            ;;
        --voice)
            VOICE="${2:-$VOICE}"
            shift 2
            ;;
        --model)
            MODEL="${2:-$MODEL}"
            shift 2
            ;;
        --duration)
            DURATION="${2:-}"
            shift 2
            ;;
        --premium)
            PREMIUM=1
            shift
            ;;
        --dry-run-script)
            DRY_RUN_SCRIPT=1
            shift
            ;;
        --skip-script)
            SKIP_SCRIPT=1
            shift
            ;;
        --skip-seed)
            SKIP_SEED=1
            shift
            ;;
        --skip-recording)
            SKIP_RECORDING=1
            shift
            ;;
        --skip-voice)
            SKIP_VOICE=1
            shift
            ;;
        --skip-sound-design)
            SKIP_SOUND_DESIGN=1
            shift
            ;;
        --help|-h)
            cat <<USAGE
Usage: ./scripts/demo-video/create-video.sh [options]

Options:
  --lang en|az|both          Content language (default: en)
  --base-url URL             Dashboard URL for recording (default: $BASE_URL)
  --output-dir DIR           Output directory (default: scripts/demo-video/output)
  --recording FILE           Existing recording to assemble instead of capturing a new one
  --voice NAME_OR_ID         ElevenLabs voice, ID, or auto warm voice (default: $VOICE)
  --model MODEL              OpenAI model (default: $MODEL)
  --duration SECONDS         Target narration/caption duration
  --premium                  Record with visible cursor, human pacing, typing, and sound design
  --dry-run-script           Generate template script/captions without OpenAI
  --skip-script              Reuse existing generated script/captions
  --skip-seed                Reuse existing local demo project data/auth context
  --skip-recording           Reuse existing recording.webm
  --skip-voice               Reuse existing voiceover MP3 files
  --skip-sound-design        Reuse existing sound-design WAV files
USAGE
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

cd "$PROJECT_ROOT"

if [[ "$SKIP_SEED" -eq 0 ]]; then
    if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx 'quorvex_ai-backend-1'; then
        echo "Seeding demo data in running backend container..."
        docker exec quorvex_ai-backend-1 \
            python /app/scripts/demo-video/seed-demo-data.py \
            --output-dir /app/scripts/demo-video/output
    else
        echo "Seeding demo data locally..."
        "$PYTHON_BIN" scripts/demo-video/seed-demo-data.py --output-dir "$OUTPUT_DIR"
    fi
fi

if [[ "$SKIP_SCRIPT" -eq 0 ]]; then
    script_args=(scripts/demo-video/generate-script.py --lang "$LANG" --model "$MODEL" --output-dir "$OUTPUT_DIR")
    if [[ -n "$DURATION" ]]; then
        script_args+=(--duration "$DURATION")
    fi
    if [[ "$DRY_RUN_SCRIPT" -eq 1 ]]; then
        script_args+=(--dry-run)
    fi
    "$PYTHON_BIN" "${script_args[@]}"
fi

if [[ "$SKIP_RECORDING" -eq 0 ]]; then
    record_args=(scripts/demo-video/record-demo.ts --base-url "$BASE_URL" --output-dir "$OUTPUT_DIR" --auth-context "$OUTPUT_DIR/demo-auth.json")
    if [[ "$PREMIUM" -eq 1 ]]; then
        record_args+=(--mode premium)
    fi
    NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-/tmp/quorvex-demo-npm-cache}" \
        npx --yes tsx "${record_args[@]}"
fi

if [[ -z "$RECORDING" ]]; then
    RECORDING="$OUTPUT_DIR/recording.webm"
fi

if [[ "$SKIP_VOICE" -eq 0 ]]; then
    "$PYTHON_BIN" scripts/demo-video/generate-voice.py --lang "$LANG" --voice "$VOICE" --output-dir "$OUTPUT_DIR"
fi

if [[ "$PREMIUM" -eq 1 && "$SKIP_SOUND_DESIGN" -eq 0 ]]; then
    if [[ "$LANG" == "en" || "$LANG" == "both" ]]; then
        "$PYTHON_BIN" scripts/demo-video/generate-sound-design.py --lang en --output-dir "$OUTPUT_DIR"
    fi
    if [[ "$LANG" == "az" || "$LANG" == "both" ]]; then
        "$PYTHON_BIN" scripts/demo-video/generate-sound-design.py --lang az --output-dir "$OUTPUT_DIR"
    fi
fi

assemble_args=(--lang "$LANG" --output-dir "$OUTPUT_DIR" --recording "$RECORDING")
if [[ "$PREMIUM" -eq 1 ]]; then
    assemble_args+=(--sound-design auto)
fi
"$SCRIPT_DIR/assemble-video.sh" "${assemble_args[@]}"
