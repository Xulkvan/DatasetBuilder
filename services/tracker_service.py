"""[STAGE1:tracker_service] IoU (ByteTrack) + ReID fallback для восстановления ID."""
from __future__ import annotations

import logging
from typing import Optional

from services.image_service import _iou_xywh
from services.reid_service import embed_from_crop as _reid_embed, cosine as _reid_cos

log = logging.getLogger("db")

IOU_MATCH_THR = 0.30
REID_MATCH_THR = 0.85
REID_MAX_LOST_FRAMES = 30


def _crop_embed(image_path: str, bbox: dict) -> list:
    try:
        from PIL import Image
        import io
        with open(image_path, "rb") as f:
            data = f.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        W, H = img.size
        x1 = int(bbox["x"] * W); y1 = int(bbox["y"] * H)
        x2 = int((bbox["x"] + bbox["w"]) * W)
        y2 = int((bbox["y"] + bbox["h"]) * H)
        if x2 <= x1 or y2 <= y1:
            return []
        crop = img.crop((x1, y1, x2, y2))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=85)
        return _reid_embed(buf.getvalue())
    except Exception:
        return []


class TrackerState:
    """Хранилище активных треков и потерянных эмбеддингов."""
    def __init__(self):
        self.track_to_aid: dict = {}
        self.lost: dict = {}    # track_id -> {aid, embedding, lost_at_frame}

    def assign_aid(self, track_id: int, aid: int) -> None:
        self.track_to_aid[track_id] = aid
        self.lost.pop(track_id, None)

    def mark_lost(self, track_id: int, aid: int, embedding: list, frame_idx: int) -> None:
        self.lost[track_id] = {"aid": aid, "embedding": embedding,
                               "lost_at": frame_idx}

    def try_recover(self, embedding: list, frame_idx: int) -> Optional[int]:
        best_aid = None
        best_cos = 0.0
        stale = []
        for tid, info in list(self.lost.items()):
            if (frame_idx - info["lost_at"]) > REID_MAX_LOST_FRAMES:
                stale.append(tid)
                continue
            c = _reid_cos(embedding, info["embedding"])
            if c > best_cos:
                best_cos, best_aid = c, info["aid"]
        for tid in stale:
            self.lost.pop(tid, None)
        if best_aid is not None and best_cos >= REID_MATCH_THR:
            return best_aid
        return None


# [PATCH:STAGE4_TRACKER_DEAD_REMOVED] match_detections_to_annotations удалён.
# [/PATCH:STAGE4_TRACKER_DEAD_REMOVED]



# [FIX-STAGE2:TRACKER-DEDUP] duplicate _crop_embed removed (see first definition above)


def process_frame_detections(frame_dets, anns, tracker_state, next_aid, image_path, frame_idx):
    """Обрабатывает детекции одного кадра, обновляет tracker_state и возвращает (updates, next_aid, assignments)."""
    updates = []
    assignments = 0
    for d in frame_dets:
        bbox = {"x": d["x"], "y": d["y"], "w": d["w"], "h": d["h"]}
        track_id = d["track_id"]

        # 1. IoU-матчинг
        best = None
        best_iou = 0.0
        for a in anns:
            iou = _iou_xywh({"x": a.x, "y": a.y, "w": a.w, "h": a.h}, bbox)
            if iou > best_iou:
                best_iou = iou
                best = a

        # 2. ReID-восстановление (если IoU не сработал)
        recovered_aid = None
        if best is None or best_iou < IOU_MATCH_THR:
            emb = _crop_embed(image_path, bbox)
            if emb:
                recovered_aid = tracker_state.try_recover(emb, frame_idx)

        if recovered_aid is not None and best is not None:
            tracker_state.assign_aid(track_id, recovered_aid)
            if best.animal_id != recovered_aid:
                best.animal_id = recovered_aid
                updates.append(best)
                assignments += 1
        elif best is not None and best_iou >= IOU_MATCH_THR:
            if track_id in tracker_state.track_to_aid:
                aid = tracker_state.track_to_aid[track_id]
            elif best.animal_id is not None:
                aid = best.animal_id
                tracker_state.assign_aid(track_id, aid)
            else:
                aid = next_aid
                next_aid += 1
                tracker_state.assign_aid(track_id, aid)

            if best.animal_id != aid:
                best.animal_id = aid
                updates.append(best)
                assignments += 1
    return updates, next_aid, assignments

