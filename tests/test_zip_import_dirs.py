"""[STAGE4] ZIP с директориями без завершающего слэша распаковывается."""
import zipfile


def test_zip_with_dir_without_slash(tmp_path):
    """Регрессия: ZipInfo("mydir") + S_IFDIR в external_attr — это директория,
    даже если имя без завершающего "/". Раньше is_dir()=False → попытка
    открыть как файл → создавался пустой файл "mydir" и падал следующий
    "mydir/file.txt" (NotADirectoryError)."""
    from services.zip_import_service import _safe_extract_zip

    zpath = tmp_path / "dirs.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        info = zipfile.ZipInfo("mydir")
        info.external_attr = (0o040755 << 16) | 0x10  # S_IFDIR | MS-DOS dir
        z.writestr(info, b"")
        z.writestr("mydir/file.txt", b"hello")

    out = tmp_path / "out"
    out.mkdir()
    with zipfile.ZipFile(zpath) as zf:
        _safe_extract_zip(zf, str(out))

    assert (out / "mydir").is_dir()
    assert (out / "mydir" / "file.txt").read_text() == "hello"
