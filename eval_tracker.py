#!/usr/bin/env python3
"""[STAGE1:eval_tracker] Базовый расчёт MOTA и IDF1.

Ожидаемые входные форматы (JSON):
  gt   = {"frames": {frame_idx: [{track_id, x, y, w, h}, ...]}}
  pred = {"frames": {frame_idx: [{track_id, x, y, w, h}, ...]}}

Использование:
  python eval_tracker.py gt.json pred.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict


def _iou(a, b):
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / ua if ua > 0 else 0.0


def _greedy_match(gt: list, pred: list, iou_thr: float = 0.5):
    pairs = []
    used_pred = set()
    for gi, g in enumerate(gt):
        best_pi = -1
        best_iou = iou_thr
        for pi, p in enumerate(pred):
            if pi in used_pred:
                continue
            i = _iou(g, p)
            if i > best_iou:
                best_iou, best_pi = i, pi
        if best_pi >= 0:
            used_pred.add(best_pi)
            pairs.append((gi, best_pi))
    return pairs


def compute_mota(gt_frames: dict, pred_frames: dict, iou_thr: float = 0.5) -> float:
    all_frames = set(gt_frames.keys()) | set(pred_frames.keys())
    fn = fp = idsw = matches = 0
    last_match = {}    # gt_id -> pred_id
    for fidx in sorted(all_frames):
        gt = gt_frames.get(fidx, [])
        pr = pred_frames.get(fidx, [])
        pairs = _greedy_match(gt, pr, iou_thr)
        matched_gt = {gi for gi, _ in pairs}
        matched_pr = {pi for _, pi in pairs}
        matches += len(pairs)
        fn += len(gt) - len(matched_gt)
        fp += len(pr) - len(matched_pr)
        for gi, pi in pairs:
            gid = gt[gi]["track_id"]
            pid = pr[pi]["track_id"]
            if gid in last_match and last_match[gid] != pid:
                idsw += 1
            last_match[gid] = pid
    total_gt = sum(len(v) for v in gt_frames.values())
    if total_gt == 0:
        return 1.0
    return max(-1.0, 1.0 - (fn + fp + idsw) / total_gt)


def compute_idf1(gt_frames: dict, pred_frames: dict, iou_thr: float = 0.5) -> float:
    # Построить граф gt_id -> pred_id по совпадениям
    counts: dict = defaultdict(lambda: defaultdict(int))
    gt_total: dict = defaultdict(int)
    pred_total: dict = defaultdict(int)
    for fidx in set(gt_frames.keys()) | set(pred_frames.keys()):
        gt = gt_frames.get(fidx, [])
        pr = pred_frames.get(fidx, [])
        pairs = _greedy_match(gt, pr, iou_thr)
        for gi, pi in pairs:
            gid = gt[gi]["track_id"]
            pid = pr[pi]["track_id"]
            counts[gid][pid] += 1
        for g in gt:
            gt_total[g["track_id"]] += 1
        for p in pr:
            pred_total[p["track_id"]] += 1
    # Жадное назначение
    assignments = []
    for gid, pm in counts.items():
        for pid, c in pm.items():
            assignments.append((c, gid, pid))
    assignments.sort(reverse=True)
    used_g, used_p = set(), set()
    idtp = 0
    for c, gid, pid in assignments:
        if gid in used_g or pid in used_p:
            continue
        used_g.add(gid); used_p.add(pid)
        idtp += c
    idp = sum(pred_total.values())
    idg = sum(gt_total.values())
    denom = idp + idg
    if denom == 0:
        return 1.0
    return 2.0 * idtp / denom


def _load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    frames = data.get("frames") if isinstance(data, dict) else None
    return frames or {}


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python eval_tracker.py gt.json pred.json", file=sys.stderr)
        return 2
    gt = _load(sys.argv[1])
    pred = _load(sys.argv[2])
    mota = compute_mota(gt, pred)
    idf1 = compute_idf1(gt, pred)
    print(f"MOTA  = {mota:.4f}")
    print(f"IDF1  = {idf1:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
