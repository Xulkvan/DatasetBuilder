# DatasetBuilder Edge Runtime

Ready-to-run ONNX inference for NVIDIA Jetson.

## Contents

- `edge_server.py` — FastAPI + onnxruntime, reads RTSP, emits JSON events
- `Dockerfile`    — Jetson image (L4T r35.x / JetPack 5.x)
- `model.onnx`    — exported ONNX model

## Quick start (Docker)

1) Build:

    docker build -f Dockerfile -t db-edge:latest .

2) Run (with RTSP camera):

    docker run --runtime nvidia --network host \
        -e EDGE_RTSP_URL="rtsp://camera.local/stream1" \
        db-edge:latest

3) Check events:

    curl http://localhost:8080/events?limit=10

## Manual (host with Python 3.10+)

    pip install fastapi uvicorn opencv-python-headless onnxruntime numpy
    export EDGE_MODEL_PATH=./model.onnx
    export EDGE_RTSP_URL=rtsp://camera.local/stream1
    python edge_server.py

## API

| Method | Endpoint          | Description                       |
|--------|-------------------|-----------------------------------|
| GET    | /health           | status, model name, parameters    |
| POST   | /stream/start     | {"url": "rtsp://..."}             |
| POST   | /stream/stop      | stop stream                       |
| GET    | /events?limit=N   | last N events                     |
| GET    | /events/stream    | SSE stream of events              |

Event JSON shape:

    {
      "ts": 1730123456.789,
      "url": "rtsp://...",
      "detections": [
        {"class_id": 0, "confidence": 0.87, "bbox": [0.1, 0.2, 0.3, 0.4]}
      ]
    }

`bbox` is normalized (0..1), format `[x, y, w, h]`.
