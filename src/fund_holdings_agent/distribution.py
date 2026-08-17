from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .candidate_confirmations import CONFIRMATION_COLUMNS


ROOT_FILES = (
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    "install.command",
    "基金持仓Agent.command",
    "需求文档.md",
)
PUBLIC_DATA_FILES = (
    "managers_portfolio.csv",
    "personnel_template.csv",
)
INTERNAL_DATA_FILES = (
    "personnel_internal_20260616.csv",
    "personnel_manual_overrides.csv",
    "resource_candidate_confirmations.csv",
)
DOC_FILES = (
    "mac_cli_distribution.md",
    "AI_AGENT_HANDOFF.md",
)


def build_mac_distribution(
    project_root: Path,
    output_dir: Path,
    *,
    include_internal_data: bool = False,
    build_date: dt.date | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    _validate_project_root(project_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    date_text = (build_date or dt.date.today()).strftime("%Y%m%d")
    mode = "internal" if include_internal_data else "framework"
    archive_stem = f"fund-holdings-agent-mac-{mode}-{date_text}"
    archive_path = output_dir / f"{archive_stem}.zip"
    if archive_path.exists():
        raise FileExistsError(f"交付包已存在，请更换输出目录或日期：{archive_path}")

    with tempfile.TemporaryDirectory(prefix="fund-agent-package-", dir=output_dir) as temporary:
        package_root = Path(temporary) / archive_stem
        package_root.mkdir()
        for name in ROOT_FILES:
            _copy_required(project_root / name, package_root / name)
        shutil.copytree(
            project_root / "src",
            package_root / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        docs_root = package_root / "docs"
        docs_root.mkdir()
        for name in DOC_FILES:
            _copy_required(project_root / "docs" / name, docs_root / name)

        data_root = package_root / "data"
        data_root.mkdir()
        for name in PUBLIC_DATA_FILES:
            _copy_required(project_root / "data" / name, data_root / name)
        if include_internal_data:
            for name in INTERNAL_DATA_FILES:
                _copy_required(project_root / "data" / name, data_root / name)
        else:
            shutil.copy2(data_root / "personnel_template.csv", data_root / "personnel_internal_20260616.csv")
            _write_empty_confirmations(data_root / "resource_candidate_confirmations.csv")

        _write_package_info(package_root, include_internal_data=include_internal_data, date_text=date_text)
        manifest = _build_manifest(package_root)
        (package_root / "PACKAGE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _assert_safe_package(package_root, include_internal_data=include_internal_data)
        _write_zip(package_root, archive_path)

    return {
        "archive": str(archive_path),
        "sha256": _sha256(archive_path),
        "size_bytes": archive_path.stat().st_size,
        "mode": mode,
        "includes_internal_data": include_internal_data,
        "file_count": manifest["file_count"] + 1,
    }


def _validate_project_root(root: Path) -> None:
    required = [root / "pyproject.toml", root / "src" / "fund_holdings_agent", root / "data"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("不是完整的基金持仓 Agent 项目目录：" + "；".join(missing))


def _copy_required(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"交付包缺少必需文件：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_empty_confirmations(path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=CONFIRMATION_COLUMNS).writeheader()


def _write_package_info(root: Path, *, include_internal_data: bool, date_text: str) -> None:
    if include_internal_data:
        scope = "内部完整版：包含研究人员库与已确认对接关系，仅限获授权的内部用户传递。"
    else:
        scope = "开发框架版：研究人员库与候选确认关系为空模板，不包含内部研究资源数据。"
    text = "\n".join(
        [
            "基金持仓 Agent Mac 交付包",
            f"构建日期：{date_text}",
            f"版本类型：{scope}",
            "",
            "安装：双击 install.command",
            "运行：双击 基金持仓Agent.command",
            "前置：macOS、Python 3.11或更高版本、可访问Python依赖源及天天基金/东方财富。",
            "",
            "提示：macOS首次打开可能需要右键选择‘打开’。正式报告默认保存到 ~/Documents/FundHoldingsAgent/。",
        ]
    )
    (root / "PACKAGE_INFO.txt").write_text(text + "\n", encoding="utf-8")


def _build_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        files.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": _sha256(path)})
    return {"schema_version": 1, "file_count": len(files), "files": files}


def _assert_safe_package(root: Path, *, include_internal_data: bool) -> None:
    forbidden_parts = {".venv", ".git", ".pytest_cache", "outputs", "__pycache__", "node_modules"}
    for path in root.rglob("*"):
        if forbidden_parts.intersection(path.relative_to(root).parts):
            raise ValueError(f"交付包意外包含运行环境或历史产物：{path}")
    if not include_internal_data:
        personnel = root / "data" / "personnel_internal_20260616.csv"
        with personnel.open("r", encoding="utf-8-sig", newline="") as handle:
            if sum(1 for _ in csv.DictReader(handle)):
                raise ValueError("开发框架版不得包含真实研究人员记录")
        confirmations = root / "data" / "resource_candidate_confirmations.csv"
        with confirmations.open("r", encoding="utf-8-sig", newline="") as handle:
            if sum(1 for _ in csv.DictReader(handle)):
                raise ValueError("开发框架版不得包含内部候选确认关系")


def _write_zip(package_root: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            archive.write(path, (Path(package_root.name) / path.relative_to(package_root)).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建可交给另一台Mac的基金持仓Agent交付包")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--include-internal-data", action="store_true", help="包含真实人员库和候选确认关系，仅限内部交付")
    args = parser.parse_args(argv)
    try:
        result = build_mac_distribution(
            args.project_root,
            args.output_dir,
            include_internal_data=args.include_internal_data,
        )
    except (OSError, ValueError) as exc:
        print(f"构建失败：{exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
