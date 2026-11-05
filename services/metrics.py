"""[PATCH:STAGE4-F-08] Prometheus metrics (no-op if prometheus_client unavailable).

Usage:
    from services.metrics import (
        images_uploaded_total, imports_completed_total,
        train_runs_total, pipeline_runs_total, autolabel_box_total,
    )
    images_uploaded_total.inc()
    train_runs_total.labels(status="done").inc()
"""
try:
    from prometheus_client import Counter as _Counter
    _METRICS_OK = True
except ImportError:
    _Counter = None
    _METRICS_OK = False


class _NoopCounter:
    def labels(self, **_kw):
        return self
    def inc(self, *_a, **_kw):
        return None


def _make(name, doc, labels=None):
    if not _METRICS_OK:
        return _NoopCounter()
    try:
        if labels:
            return _Counter(name, doc, labels)
        return _Counter(name, doc)
    except Exception:
        # Duplicated timeseries (при importlib.reload) или иная ошибка —
        # откатываемся на no-op, чтобы не падать в проде.
        return _NoopCounter()


images_uploaded_total = _make(
    "images_uploaded_total",
    "Total images uploaded across all sources",
)
imports_completed_total = _make(
    "imports_completed_total",
    "Total import operations completed",
    ["source"],
)
train_runs_total = _make(
    "train_runs_total",
    "Total training runs (done/error/stopped)",
    ["status"],
)
pipeline_runs_total = _make(
    "pipeline_runs_total",
    "Total pipeline runs (done/error/stopped)",
    ["status"],
)
autolabel_box_total = _make(
    "autolabel_box_total",
    "Total bounding boxes produced by autolabeling",
)
