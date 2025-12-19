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
    body = json.dumps({"prompt": prompt, "client_id": CLIENT_ID}).encode("utf-8")
    req = urllib.request.Request(url, body)
    return json.loads(urllib.request.urlopen(req).read())

def get_history(prompt_id):
    url = f"http://{SERVER_ADDRESS}:8188/history/{prompt_id}"
    return json.loads(urllib.request.urlopen(url).read())

def wait_for_video(ws, prompt):
    prompt_id = queue_prompt(prompt)["prompt_id"]

    # wait for completion
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

    # Look for VHS_VideoCombine outputs: videos[0].fullpath OR filenames[0]
    for node_output in history.get("outputs", {}).values():
        vids = node_output.get("videos") or []
        if vids:
            fullpath = vids[0].get("fullpath")
            filename = vids[0].get("filename")
            if fullpath:
                return fullpath
            if filename:
                return os.path.join("/ComfyUI/output", filename)
        fns = node_output.get("filenames") or []
        if fns:
            return os.path.join("/ComfyUI/output", fns[0])

    return None

def handler(job):
    inp = job.get("input", {})
    task_dir = f"/tmp/{uuid.uuid4()}"
    os.makedirs(task_dir, exist_ok=True)

    # image input
    if "image_base64" in inp:
        image_path = save_base64(inp["image_base64"], f"{task_dir}/input.jpg")
    elif "image_url" in inp:
        image_path = download(inp["image_url"], f"{task_dir}/input.jpg")
    elif "image_path" in inp:
        image_path = inp["image_path"]
    else:
        return {"error": "No input image provided"}

    # workflow
    engine = inp.get("engine", "fp8")
    workflow_path = "/new_Wan22_gguf_api.json" if engine == "gguf" else "/new_Wan22_api.json"
    prompt = load_json(workflow_path)

    # params
    prompt["244"]["inputs"]["image"] = image_path
    prompt["541"]["inputs"]["num_frames"] = inp.get("length", 81)
    prompt["135"]["inputs"]["positive_prompt"] = inp.get("prompt", "")
    prompt["135"]["inputs"]["negative_prompt"] = inp.get("negative_prompt", "")
    prompt["235"]["inputs"]["value"] = to_16(inp.get("width", 640))
    prompt["236"]["inputs"]["value"] = to_16(inp.get("height", 360))

    # run ComfyUI
    ws = websocket.WebSocket()
    ws.connect(f"ws://{SERVER_ADDRESS}:8188/ws?clientId={CLIENT_ID}")

    video_path = wait_for_video(ws, prompt)
    ws.close()

    if not video_path or not os.path.exists(video_path):
        return {"error": "Video not generated"}

    # copy to network volume
    output_dir = "/runpod-volume/output"
    os.makedirs(output_dir, exist_ok=True)
    final_path = f"{output_dir}/wan22_{int(time.time())}.mp4"
    shutil.copy2(video_path, final_path)

    return {"video_path": final_path}

runpod.serverless.start({"handler": handler})
