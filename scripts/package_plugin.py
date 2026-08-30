"""Create a clean, installable QGIS Copilot plugin ZIP without local data or secrets."""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "qgis_copilot"
REQUIRED_FILES = ("__init__.py", "metadata.txt")
EXCLUDED_DIRECTORY_NAMES = {"__pycache__", ".git", ".pytest_cache"}
EXCLUDED_FILE_PATTERNS = ("*.pyc", "*.pyo", "*.key", "*.pem", ".env", ".env.*")


def package_files(package_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_DIRECTORY_NAMES for part in path.parts):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILE_PATTERNS):
            continue
        files.append(path)
    return files


def validate_package_source(package_root: Path, license_path: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (package_root / name).is_file()]
    if missing:
        raise ValueError(f"插件源目录缺少必需文件：{', '.join(missing)}")
    if not license_path.is_file():
        raise ValueError("项目根目录缺少 LICENSE。")


def build_plugin_zip(project_root: Path, output_path: Path) -> list[str]:
    package_root = project_root / PACKAGE_NAME
    license_path = project_root / "LICENSE"
    validate_package_source(package_root, license_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    members: list[str] = []
    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        for path in package_files(package_root):
            arcname = Path(PACKAGE_NAME) / path.relative_to(package_root)
            archive.write(path, arcname.as_posix())
            members.append(arcname.as_posix())
        archive.write(license_path, f"{PACKAGE_NAME}/LICENSE")
        members.append(f"{PACKAGE_NAME}/LICENSE")
    validate_plugin_zip(output_path)
    return members


def validate_plugin_zip(zip_path: Path) -> None:
    with ZipFile(zip_path) as archive:
        names = archive.namelist()
    if not names or any(not name.startswith(f"{PACKAGE_NAME}/") for name in names):
        raise ValueError("插件 ZIP 必须只包含一个顶层 qgis_copilot/ 目录。")
    required_members = {f"{PACKAGE_NAME}/{name}" for name in REQUIRED_FILES} | {f"{PACKAGE_NAME}/LICENSE"}
    missing = sorted(required_members - set(names))
    if missing:
        raise ValueError(f"插件 ZIP 缺少必需成员：{', '.join(missing)}")
    unsafe = [name for name in names if "/.git/" in name or "__pycache__" in name or name.endswith((".pyc", ".key", ".pem"))]
    if unsafe:
        raise ValueError(f"插件 ZIP 包含禁止成员：{', '.join(unsafe)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist" / "qgis_copilot.zip")
    args = parser.parse_args(argv)
    members = build_plugin_zip(PROJECT_ROOT, args.output.resolve())
    print(f"已创建插件包：{args.output.resolve()}")
    print(f"ZIP 成员数：{len(members)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
