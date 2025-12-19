import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import subprocess
import time
import binascii

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

server_address = os.getenv("SERVER_ADDRESS", "127.0.0.1")
client_id = str(uuid.uuid4())

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
    url = f"http://{server_address}:8188/prompt"
    body = json.dumps({"prompt": prompt, "client_id": client_id}).encode()
    req = urllib.request.Request(url, body)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(pid):
    url = f"http://{server_address}:8188/history/{pid}"
    return json.loads(urllib.request.urlopen(url).read())

def wait_for_video(ws, prompt):
    pid = queue_prompt(prompt)["prompt_id"]

    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data["type"] == "executing":
                if data["data"]["node"] is None and data["data"]["prompt_id"] == pid:
                    break

    history = get_history(pid)[pid]
    for node in history["outputs"].values():
        if "gifs" in node:
            video = node["gifs"][0]["fullpath"]
            with open(video, "rb") as f:
                return base64.b64encode(f.read()).decode()

    return None

# ------------------------
# Main Handler
# ------------------------

def handler(job):
    inp = job.get("input", {})
    task = f"/tmp/{uuid.uuid4()}"
    os.makedirs(task, exist_ok=True)

    # ---------- image ----------
    if "image_base64" in inp:
        image = save_base64(inp["image_base64"], f"{task}/input.jpg")
    elif "image_url" in inp:
        image = download(inp["image_url"], f"{task}/input.jpg")
    elif "image_path" in inp:
        image = inp["image_path"]
    else:
        image = "/example_image.png"

    end_image = None
    if "end_image_base64" in inp:
        end_image = save_base64(inp["end_image_base64"], f"{task}/end.jpg")
    elif "end_image_url" in inp:
        end_image = download(inp["end_image_url"], f"{task}/end.jpg")
    elif "end_image_path" in inp:
        end_image = inp["end_image_path"]

    # ---------- engine selection ----------
    engine = inp.get("engine", "fp8")

    if engine == "gguf":
        workflow_path = "/new_Wan22_gguf_api.json"
    elif engine == "flf2v":
        workflow_path = "/new_Wan22_flf2v_api.json"
    elif end_image:
        workflow_path = "/new_Wan22_flf2v_api.json"
    else:
        workflow_path = "/new_Wan22_api.json"

    logger.info(f"Using workflow: {workflow_path}")

    prompt = load_json(workflow_path)

    # ---------- params ----------
    width  = to_16(inp.get("width", 480))
    height = to_16(inp.get("height", 832))
    length = inp.get("length", 81)
    steps  = inp.get("steps", 10)
    seed   = inp.get("seed", 42)
    cfg    = inp.get("cfg", 2.0)

    # ---------- inject ----------
    prompt["244"]["inputs"]["image"] = image
    prompt["541"]["inputs"]["num_frames"] = length
    prompt["135"]["inputs"]["positive_prompt"] = inp["prompt"]
    prompt["135"]["inputs"]["negative_prompt"] = inp.get("negative_prompt", "")
    prompt["220"]["inputs"]["seed"] = seed
    prompt["540"]["inputs"]["seed"] = seed
    prompt["540"]["inputs"]["cfg"] = cfg
    prompt["235"]["inputs"]["value"] = width
    prompt["236"]["inputs"]["value"] = height
    prompt["498"]["inputs"]["context_frames"] = length
    prompt["498"]["inputs"]["context_overlap"] = inp.get("context_overlap", 48)

    if end_image and "617" in prompt:
        prompt["617"]["inputs"]["image"] = end_image

    # ---------- run ----------
    ws_url = f"ws://{server_address}:8188/ws?clientId={client_id}"
    ws = websocket.WebSocket()

    for _ in range(60):
        try:
            ws.connect(ws_url)
            break
        except:
            time.sleep(1)

    video_b64 = wait_for_video(ws, prompt)
    ws.close()

    if not video_b64:
        return {"error": "Video not found"}

    return {
        "video": f"data:video/mp4;base64,{video_b64}"
    }

runpod.serverless.start({"handler": handler})
