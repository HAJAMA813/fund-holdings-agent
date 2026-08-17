import datetime as dt
from pathlib import Path

import pytest

from fund_holdings_agent.distribution import build_mac_distribution

INTERNAL_DATA_PRESENT = (Path("data") / "personnel_internal_20260616.csv").exists()


def test_mac_installer_uses_regular_install_instead_of_editable_pth() -> None:
    installer = Path("install.command").read_text(encoding="utf-8")
    assert "pip install --upgrade ." in installer
    assert "pip install -e" not in installer
    assert "import fund_holdings_agent, lxml, openpyxl" in installer
    assert "reportlab" in installer


def test_mac_launcher_uses_installed_entrypoint() -> None:
    launcher = Path("基金持仓Agent.command").read_text(encoding="utf-8")
    assert ".venv/bin/fund-agent" in launcher


def test_framework_distribution_excludes_internal_records(tmp_path: Path) -> None:
    result = build_mac_distribution(Path.cwd(), tmp_path, build_date=dt.date(2026, 8, 16))
    archive = Path(result["archive"])
    assert archive.exists()
    assert result["mode"] == "framework"
    import zipfile

    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        assert not any(".venv" in name or "outputs/" in name for name in names)
        personnel_name = next(name for name in names if name.endswith("data/personnel_internal_20260616.csv"))
        confirmations_name = next(name for name in names if name.endswith("data/resource_candidate_confirmations.csv"))
        assert handle.read(personnel_name).decode("utf-8-sig").count("\n") == 1
        assert handle.read(confirmations_name).decode("utf-8-sig").count("\n") == 1


@pytest.mark.skipif(not INTERNAL_DATA_PRESENT, reason="内部人员库未提供；公开克隆只验证框架版")
def test_internal_distribution_contains_authorized_business_data(tmp_path: Path) -> None:
    result = build_mac_distribution(
        Path.cwd(),
        tmp_path,
        include_internal_data=True,
        build_date=dt.date(2026, 8, 16),
    )
    assert result["mode"] == "internal"
    assert result["includes_internal_data"] is True
