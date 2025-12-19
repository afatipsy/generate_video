import runpod
import os
import json
import uuid
import time
import logging
import urllib.request
import subprocess
import websocket
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "127.0.0.1")
CLIENT_ID = str(uuid.uuid4())
OUTPUT_DIR = "/runpod-volume/output"


def to_nearest_multiple_of_16(value):
    v = int(round(float(value) / 16.0) * 16)
    return max(v, 16)


def download_file(url, out_path):
    subprocess.run(
        ["wget", "-O", out_path, "--no-verbose", url],
        check=True
    )
    return out_path


def load_workflow(path):
    with open(path, "r") as f:
        return json.load(f)


def queue_prompt(prompt):
    url = f"http://{SERVER_ADDRESS}:8188/prompt"
    payload = {"prompt": prompt, "client_id": CLIENT_ID}
    req = urllib.request.Request(url, json.dumps(payload).encode())
    return json.loads(urllib.request.urlopen(req).read())


def get_history(prompt_id):
    url = f"http://{SERVER_ADDRESS}:8188/history/{prompt_id}"
    return json.loads(urllib.request.urlopen(url).read())


def wait_for_comfy():
    url = f"http://{SERVER_ADDRESS}:8188/"
    for _ in range(180):
        try:
            urllib.request.urlopen(url, timeout=3)
            return
        except:
            time.sleep(1)
    raise RuntimeError("ComfyUI not reachable")


def get_video_and_save(prompt, task_id):
    prompt_id = queue_prompt(prompt)["prompt_id"]

    ws = websocket.WebSocket()
    ws.connect(f"ws://{SERVER_ADDRESS}:8188/ws?clientId={CLIENT_ID}")

    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data["type"] == "executing":
                if data["data"]["node"] is None and data["data"]["prompt_id"] == prompt_id:
                    break

    ws.close()

    history = get_history(prompt_id)[prompt_id]

    for node in history["outputs"].values():
        if "gifs" in node:
            src = node["gifs"][0]["fullpath"]
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            dst = f"{OUTPUT_DIR}/{task_id}.mp4"
            shutil.copy(src, dst)
            return dst

    return None


def handler(job):
    job_input = job.get("input", {})
    task_id = f"wan22_{uuid.uuid4().hex}"

    wait_for_comfy()

    # image
    if "image_url" in job_input:
        image_path = f"/tmp/{task_id}.jpg"
        download_file(job_input["image_url"], image_path)
    elif "image_path" in job_input:
        image_path = job_input["image_path"]
    else:
        raise ValueError("image_url or image_path required")

    workflow = load_workflow("/new_Wan22_api.json")

    width = to_nearest_multiple_of_16(job_input.get("width", 640))
    height = to_nearest_multiple_of_16(job_input.get("height", 360))
    length = int(job_input.get("length", 75))
    steps = int(job_input.get("steps", 10))

    workflow["244"]["inputs"]["image"] = image_path
    workflow["541"]["inputs"]["num_frames"] = length
    workflow["135"]["inputs"]["positive_prompt"] = job_input["prompt"]
    workflow["135"]["inputs"]["negative_prompt"] = job_input.get("negative_prompt", "")
    workflow["235"]["inputs"]["value"] = width
    workflow["236"]["inputs"]["value"] = height
    workflow["498"]["inputs"]["context_frames"] = length
    workflow["498"]["inputs"]["context_overlap"] = job_input.get("context_overlap", 48)
    workflow["540"]["inputs"]["cfg"] = job_input.get("cfg", 2.0)
    workflow["540"]["inputs"]["seed"] = job_input.get("seed", 42)

    if "834" in workflow:
        workflow["834"]["inputs"]["steps"] = steps
        workflow["829"]["inputs"]["step"] = int(steps * 0.6)

    video_path = get_video_and_save(workflow, task_id)

    if not video_path:
        return {"error": "Video not generated"}

    return {
        "video_path": video_path
    }


runpod.serverless.start({"handler": handler})
