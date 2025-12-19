import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import subprocess
import time
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "127.0.0.1")
CLIENT_ID = str(uuid.uuid4())

# ------------------------
# Helpers
# ------------------------

def to_16(x):
    return max(16, int(round(int(x) / 16) * 16))

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)

def save_base64(data, path):
    data = data.split(",")[-1]
    with open(path, "wb") as f:
        f.write(base64.b64decode(data))
    return path

def download(url, path):
    subprocess.run(["wget", "-q", "-O", path, url], check=True)
    return path

def queue_prompt(prompt):
    url = f"http://{SERVER_ADDRESS}:8188/prompt"
    body = json.dumps({
        "prompt": prompt,
        "client_id": CLIENT_ID
    }).encode("utf-8")

    req = urllib.request.Request(url, body)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(prompt_id):
    url = f"http://{SERVER_ADDRESS}:8188/history/{prompt_id}"
    return json.loads(urllib.request.urlopen(url).read())

def wait_for_video(ws, prompt):
    prompt_id = queue_prompt(prompt)["prompt_id"]

    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            data = json.loads(msg)
            if (
                data.get("type") == "executing"
                and data["data"]["node"] is None
                and data["data"]["prompt_id"] == prompt_id
            ):
                break

    history = get_history(prompt_id)[prompt_id]

    for node in history.get("outputs", {}).values():
        if "gifs" in node and node["gifs"]:
            return node["gifs"][0]["fullpath"]

    return None

# ------------------------
# Main Handler
# ------------------------

def handler(job):
    inp = job.get("input", {})
    task_dir = f"/tmp/{uuid.uuid4()}"
    os.makedirs(task_dir, exist_ok=True)

    # -------- image input --------
    if "image_base64" in inp:
        image_path = save_base64(inp["image_base64"], f"{task_dir}/input.jpg")
    elif "image_url" in inp:
        image_path = download(inp["image_url"], f"{task_dir}/input.jpg")
    elif "image_path" in inp:
        image_path = inp["image_path"]
    else:
        return {"error": "No input image provided"}

    end_image_path = None
    if "end_image_base64" in inp:
        end_image_path = save_base64(inp["end_image_base64"], f"{task_dir}/end.jpg")
    elif "end_image_url" in inp:
        end_image_path = download(inp["end_image_url"], f"{task_dir}/end.jpg")
    elif "end_image_path" in inp:
        end_image_path = inp["end_image_path"]

    # -------- workflow selection --------
    engine = inp.get("engine", "fp8")

    if engine == "gguf":
        workflow_path = "/new_Wan22_gguf_api.json"
    elif engine == "flf2v" or end_image_path:
        workflow_path = "/new_Wan22_flf2v_api.json"
    else:
        workflow_path = "/new_Wan22_api.json"

    logger.info(f"Using workflow: {workflow_path}")

    prompt = load_json(workflow_path)

    # -------- parameters --------
    width  = to_16(inp.get("width", 480))
    height = to_16(inp.get("height", 832))
    length = inp.get("length", 81)
    seed   = inp.get("seed", 42)
    cfg    = inp.get("cfg", 2.0)

    # -------- inject --------
    prompt["244"]["inputs"]["image"] = image_path
    prompt["541"]["inputs"]["num_frames"] = length
    prompt["135"]["inputs"]["positive_prompt"] = inp.get("prompt", "")
    prompt["135"]["inputs"]["negative_prompt"] = inp.get("negative_prompt", "")
    prompt["220"]["inputs"]["seed"] = seed
    prompt["540"]["inputs"]["seed"] = seed
    prompt["540"]["inputs"]["cfg"] = cfg
    prompt["235"]["inputs"]["value"] = width
    prompt["236"]["inputs"]["value"] = height
    prompt["498"]["inputs"]["context_frames"] = length
    prompt["498"]["inputs"]["context_overlap"] = inp.get("context_overlap", 48)

    if end_image_path and "617" in prompt:
        prompt["617"]["inputs"]["image"] = end_image_path

    # -------- run ComfyUI --------
    ws_url = f"ws://{SERVER_ADDRESS}:8188/ws?clientId={CLIENT_ID}"
    ws = websocket.WebSocket()

    for _ in range(60):
        try:
            ws.connect(ws_url)
            break
        except Exception:
            time.sleep(1)

    video_path = wait_for_video(ws, prompt)
    ws.close()

    if not video_path or not os.path.exists(video_path):
        return {"error": "Video not generated"}

    # -------- SERVERLESS OUTPUT (THIS IS THE IMPORTANT PART) --------
    output_dir = "/runpod-volume/output"
    os.makedirs(output_dir, exist_ok=True)

    final_path = f"{output_dir}/wan22_{int(time.time())}.mp4"
    shutil.copy2(video_path, final_path)

    return {
        "file_path": final_path
    }

runpod.serverless.start({
    "handler": handler
})
