"""[PATCH:STAGE3_2:edge-server]
Lightweight ONNX Edge runtime for DatasetBuilder.

Accepts an ONNX model + RTSP stream, emits JSON events per frame.

Environment:
    EDGE_MODEL_PATH   path to .onnx model (required)
    EDGE_RTSP_URL     optional, auto-start stream on boot
    EDGE_CONF         confidence threshold (default 0.25)
    EDGE_IOU          NMS IoU (default 0.45)
    EDGE_IMGSZ        input size (default 640)
    EDGE_PORT         server port (default 8080)

Endpoints:
    GET  /health
    POST /stream/start  {"url": "rtsp://..."}
    POST /stream/stop
    GET  /events?limit=N
    GET  /events/stream  (SSE)
"""

import os
import json
import time
import asyncio
import threading
from collections import deque
from typing import Optional

import cv2
import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn


MODEL_PATH = os.environ.get("EDGE_MODEL_PATH", "")
RTSP_URL = os.environ.get("EDGE_RTSP_URL", "")
CONF = float(os.environ.get("EDGE_CONF", "0.25"))
IOU = float(os.environ.get("EDGE_IOU", "0.45"))
IMGSZ = int(os.environ.get("EDGE_IMGSZ", "640"))
PORT = int(os.environ.get("EDGE_PORT", "8080"))

if not MODEL_PATH or not os.path.exists(MODEL_PATH):
    raise RuntimeError(f"EDGE_MODEL_PATH not set or file missing: {MODEL_PATH!r}")

session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
input_name = session.get_inputs()[0].name


app = FastAPI(title="DatasetBuilder Edge Runtime")


class StreamIn(BaseModel):
    url: str


_state = {
    "running": False,
    "url": None,
    "events": deque(maxlen=500),
    "last_frame_at": None,
    "fps": 0.0,
}
_lock = threading.Lock()
_stop_evt = threading.Event()
_worker: Optional[threading.Thread] = None


def _preprocess(frame_bgr, imgsz):
    h0, w0 = frame_bgr.shape[:2]
    s = min(imgsz / h0, imgsz / w0)
    nh, nw = int(h0 * s), int(w0 * s)
    resized = cv2.resize(frame_bgr, (nw, nh))
    canvas = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
    ox, oy = (imgsz - nw) // 2, (imgsz - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = resized
    x = canvas[:, :, ::-1].astype(np.float32) / 255.0
    x = np.transpose(x, (2, 0, 1))[None, ...]
    return np.ascontiguousarray(x, dtype=np.float32), (s, ox, oy, h0, w0)


def _postprocess(out, meta, conf, iou):
    s, ox, oy, h0, w0 = meta
    arr = out
    if not isinstance(arr, np.ndarray) or arr.ndim != 3:
        return []
    if arr.shape[1] < arr.shape[2]:
        arr = np.transpose(arr, (0, 2, 1))
    arr = arr[0]
    xywh = arr[:, :4]
    scores = arr[:, 4:]
    if scores.shape[1] == 0:
        return []
    cls_ids = scores.argmax(axis=1)
    confs = scores.max(axis=1)
    mask = confs >= conf
    if not mask.any():
        return []
    xywh, confs, cls_ids = xywh[mask], confs[mask], cls_ids[mask]
    cx, cy, w, h = xywh[:, 0], xywh[:, 1], xywh[:, 2], xywh[:, 3]
    x1 = (cx - w / 2 - ox) / s
    y1 = (cy - h / 2 - oy) / s
    x2 = (cx + w / 2 - ox) / s
    y2 = (cy + h / 2 - oy) / s
    idxs = cv2.dnn.NMSBoxes(
        bboxes=[[float(a), float(b), float(c - a), float(d - b)]
                for a, b, c, d in zip(x1, y1, x2, y2)],
        scores=[float(c) for c in confs],
        score_threshold=float(conf),
        nms_threshold=float(iou),
    )
    if len(idxs) == 0:
        return []
    out_list = []
    for i in np.array(idxs).flatten().tolist():
        bx, by = float(x1[i]), float(y1[i])
        bw, bh = float(x2[i] - x1[i]), float(y2[i] - y1[i])
        out_list.append({
            "class_id": int(cls_ids[i]),
            "confidence": round(float(confs[i]), 4),
            "bbox": [
                round(max(0.0, bx / w0), 5),
                round(max(0.0, by / h0), 5),
                round(max(0.0, bw / w0), 5),
                round(max(0.0, bh / h0), 5),
            ],
        })
    return out_list


def _worker_loop(url: str):
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        with _lock:
            _state["running"] = False
        return
    last = time.time()
    frames = 0
    try:
        while not _stop_evt.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.2)
                continue
            try:
                inp, meta = _preprocess(frame, IMGSZ)
                outs = session.run(None, {input_name: inp})
                dets = _postprocess(outs[0], meta, CONF, IOU)
            except Exception:
                time.sleep(0.05)
                continue
            now = time.time()
            with _lock:
                _state["events"].append({
                    "ts": round(now, 3),
                    "url": url,
                    "detections": dets,
                })
                _state["last_frame_at"] = now
                frames += 1
                if now - last >= 1.0:
                    _state["fps"] = round(frames / (now - last), 2)
                    frames = 0
                    last = now
    finally:
        cap.release()
        with _lock:
            _state["running"] = False


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": os.path.basename(MODEL_PATH),
        "conf": CONF, "iou": IOU, "imgsz": IMGSZ,
        "running": _state["running"],
    }


@app.post("/stream/start")
def stream_start(payload: StreamIn):
    global _worker
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "Stream already running")
        _state["running"] = True
        _state["url"] = url
        _state["events"].clear()
    _stop_evt.clear()
    _worker = threading.Thread(target=_worker_loop, args=(url,), daemon=True)
    _worker.start()
    return {"status": "started", "url": url}


@app.post("/stream/stop")
def stream_stop():
    _stop_evt.set()
    with _lock:
        _state["running"] = False
    return {"status": "stopped"}


@app.get("/events")
def get_events(limit: int = 50):
    with _lock:
        items = list(_state["events"])
        return {
            "items": items[-limit:],
            "running": _state["running"],
            "fps": _state["fps"],
            "url": _state["url"],
        }


@app.get("/events/stream")
async def events_stream():
    async def gen():
        last_idx = 0
        while True:
            await asyncio.sleep(1.0)
            with _lock:
                items = list(_state["events"])
                running = _state["running"]
                fps = _state["fps"]
            if len(items) > last_idx:
                for ev in items[last_idx:]:
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                last_idx = len(items)
            else:
                yield f": keepalive fps={fps} running={running}\n\n"
            if not running and not items:
                yield "event: done\ndata: {}\n\n"
                break
    return StreamingResponse(gen(), media_type="text/event-stream")


if RTSP_URL:
    try:
        stream_start(StreamIn(url=RTSP_URL))
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
