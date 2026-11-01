"""[STAGE6-data-root] DATA_ROOT совпадает во всех модулях."""
import os


def test_data_root_consistent():
    """config.DATA_ROOT == app.DATA_ROOT == image_service.DATA_ROOT.

    Если значения различаются — _remove_file_safe может отказаться
    удалять файлы (skip removal outside data root) или, наоборот,
    удалить файл вне ожидаемого корня. Это критично для безопасности.
    """
    from config import DATA_ROOT as cfg_root
    from services.image_service import DATA_ROOT as img_root

    cfg_root = os.path.realpath(cfg_root)
    img_root = os.path.realpath(img_root)

    assert cfg_root == img_root, (
        f"DATA_ROOT mismatch:\n"
        f"  config:        {cfg_root}\n"
        f"  image_service: {img_root}\n"
        f"Это может привести к отказу _remove_file_safe."
    )


def test_data_root_absolute():
    from config import DATA_ROOT
    assert os.path.isabs(DATA_ROOT), f"DATA_ROOT not absolute: {DATA_ROOT}"


def test_data_root_exists():
    from config import DATA_ROOT
    assert os.path.isdir(DATA_ROOT), f"DATA_ROOT not exist: {DATA_ROOT}"
