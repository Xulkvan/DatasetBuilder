# clean_exe.py
import os
import shutil

DIST_DIR = os.path.join("dist", "DatasetBuilder")

def clean():
    if not os.path.isdir(DIST_DIR):
        print(f"[-] Папка {DIST_DIR} не найдена. Сначала запусти: pyinstaller build.spec")
        return

    print("🧹 Начинаю очистку мусора после сборки...")
    deleted_size = 0
    deleted_count = 0

    # Удаляем только исходники C++, тесты и дебаг-символы.
    # НИ В КОЕМ СЛУЧАЕ НЕ УДАЛЯЕМ .pyd и .dll !
    bad_dirs = {"include", "tests", "test", "__pycache__"}
    bad_exts = {".h", ".hpp", ".c", ".cpp", ".pdb", ".exp", ".lib"}

    for root, dirs, files in os.walk(DIST_DIR):
        for d in list(dirs):
            if d.lower() in bad_dirs:
                path = os.path.join(root, d)
                try:
                    for r, _, f in os.walk(path):
                        for file in f:
                            deleted_size += os.path.getsize(os.path.join(r, file))
                    shutil.rmtree(path)
                    dirs.remove(d)
                    deleted_count += 1
                except Exception:
                    pass

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in bad_exts:
                path = os.path.join(root, f)
                try:
                    deleted_size += os.path.getsize(path)
                    os.remove(path)
                    deleted_count += 1
                except Exception:
                    pass

    mb = deleted_size / (1024 * 1024)
    print(f"✅ Очистка завершена! Удалено: {deleted_count} объектов.")
    print(f"💾 Освобождено места: {mb:.2f} МБ")

if __name__ == "__main__":
    clean()
