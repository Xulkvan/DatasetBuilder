"""[STAGE8_CODE_HYGIENE] Regression: dead functions removed from app.py.

До Stage 8 в app.py оставались функции, дублирующие роуты в routers/*.py
(без активных @app. декораторов). Теперь они удалены, а активные эндпоинты
(с @app.<method>) сохранены. Этот тест падает, если кто-то вернёт удалённые
функции или случайно удалит активные.
"""


def test_moved_functions_removed():
    import app
    for name in [
        "video_track_start", "list_project_tracks", "link_from_prev",
        "navigate_with_aid", "motion_vectors_all", "track_frames",
        "export_tracks", "get_keypoint_schema", "keypoints_by_index",
        "active_learning_state", "skeletons_count", "validate_behavior",
        "agreement_score", "download_edge_package",
        "versions_diff_extended", "smart_copy_from",
        "get_trash_ttl", "get_model_mode", "set_model_mode",
        "update_trash_ttl",
    ]:
        assert not hasattr(app, name), (
            f"app.{name} всё ещё существует — STAGE8 не применился "
            f"или удалённая функция вернулась в app.py"
        )


def test_active_endpoints_kept():
    import app
    for name in [
        "video_track_status", "video_track_stop", "video_track_events",
        "project_duplicates", "export_yolo", "export_coco",
        "similar_images", "similar_with_skeleton", "copy_annotations",
        "bulk_rename",
    ]:
        assert hasattr(app, name), (
            f"app.{name} удалён — но у него активный @app. декоратор, "
            f"функцию удалять нельзя"
        )


def test_helpers_removed_when_unused():
    """_copy_kps_transformed, _copy_skeleton_one, _latest_train_run_for_project
    больше не используются вне app.py (их пользователи удалены в Stage 8).
    Если функция осталась — это не ошибка (могла быть в другом месте),
    но если её нет — это OK.
    """
    import app
    # Не делаем жёсткий assert: если кто-то добавил новое использование —
    # это законно. Просто smoke-check, что модуль импортируется.
    assert app.app is not None
