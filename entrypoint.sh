#!/bin/bash
set -e

echo "🔗 Preparing Network Volume output directory..."
mkdir -p /runpod-volume/output

# Force ComfyUI to write outputs to Network Volume
export COMFYUI_OUTPUT_DIR=/runpod-volume/output

# Optional safety symlink (covers hardcoded paths in workflows)
rm -rf /ComfyUI/output
ln -s /runpod-volume/output /ComfyUI/output

echo "📁 ComfyUI output dir -> /runpod-volume/output"

# Start ComfyUI
echo "🚀 Starting ComfyUI..."
python /ComfyUI/main.py --listen --use-sage-attention &

# Wait for ComfyUI
echo "⏳ Waiting for ComfyUI..."
max_wait=120
elapsed=0

until curl -sf http://127.0.0.1:8188/ > /dev/null; do
    sleep 2
    elapsed=$((elapsed + 2))
    echo "Waiting... ${elapsed}s"
    if [ $elapsed -ge $max_wait ]; then
        echo "❌ ComfyUI failed to start"
        exit 1
    fi
done

echo "✅ ComfyUI is ready"

# Start RunPod handler (foreground, REQUIRED)
echo "🎯 Starting handler..."
exec python handler.py
