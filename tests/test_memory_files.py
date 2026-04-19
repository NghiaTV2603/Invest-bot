import pytest

from vnstock_bot.memory import files


def test_write_and_read_roundtrip():
    mf = files.write_memory_file(
        layer="user_prefs",
        key="risk_profile",
        body="Tôi risk-averse, max 10% NAV/mã, tránh UPCOM.",
        frontmatter={"title": "Risk profile", "description": "User rules"},
    )
    assert mf.name == "risk_profile"
    assert mf.title == "Risk profile"

    loaded = files.read_memory_file("user_prefs", "risk_profile")
    assert loaded is not None
    assert loaded.body.startswith("Tôi risk-averse")
    assert loaded.description == "User rules"


def test_default_title_falls_back_to_key():
    mf = files.write_memory_file(
        layer="project",
        key="default_watchlist",
        body="FPT VNM HPG",
    )
    assert mf.title == "default watchlist"  # underscore → space


def test_invalid_key_rejected():
    with pytest.raises(ValueError):
        files.write_memory_file(layer="user_prefs", key="../etc/passwd", body="x")


def test_invalid_layer_rejected():
    with pytest.raises(ValueError):
        files.write_memory_file(layer="bogus", key="x", body="y")  # type: ignore[arg-type]


def test_list_memory_files_scans_all_layers():
    files.write_memory_file("user_prefs", "a", "aa")
    files.write_memory_file("project", "b", "bb")
    files.write_memory_file("reference", "c", "cc")
    all_files = files.list_memory_files()
    names = {(f.layer, f.name) for f in all_files}
    assert ("user_prefs", "a") in names
    assert ("project", "b") in names
    assert ("reference", "c") in names


def test_list_memory_files_filtered_by_layer():
    files.write_memory_file("user_prefs", "only_me", "x")
    only = files.list_memory_files("user_prefs")
    assert all(f.layer == "user_prefs" for f in only)


def test_delete_memory_file():
    files.write_memory_file("reference", "to_delete", "bye")
    assert files.delete_memory_file("reference", "to_delete") is True
    assert files.read_memory_file("reference", "to_delete") is None
    # idempotent
    assert files.delete_memory_file("reference", "to_delete") is False


def test_read_file_without_frontmatter():
    # simulate a hand-edited file (no frontmatter)
    from vnstock_bot.config import get_settings
    path = get_settings().absolute_memory_dir / "project" / "raw.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("chỉ có body thôi\n", encoding="utf-8")
    mf = files.read_memory_file("project", "raw")
    assert mf is not None
    assert mf.body.strip() == "chỉ có body thôi"
    assert mf.frontmatter == {}
