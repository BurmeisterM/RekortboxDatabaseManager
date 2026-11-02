from pathlib import Path
import xml.etree.ElementTree as ET

from rekordbox_manager.database import default_database


def write_settings(root, version, directory):
    path = root / "Pioneer" / version / "rekordbox3.settings"
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = ET.Element("PROPERTIES")
    ET.SubElement(settings, "VALUE", name="masterDbDirectory", val=str(directory))
    ET.ElementTree(settings).write(path, encoding="utf-8", xml_declaration=True)
    return path


def test_settings_prefer_v7_then_v6_then_standard_path(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    databases = [tmp_path / name / "master.db" for name in ("Externe Sammlung & Musik", "v6", "Pioneer/rekordbox")]
    for database in databases:
        database.parent.mkdir(parents=True, exist_ok=True)
        database.touch()
    write_settings(tmp_path, "rekordbox7", databases[0].parent)
    write_settings(tmp_path, "rekordbox6", databases[1].parent)
    for expected in databases:
        assert default_database() == expected
        expected.unlink()  # only this test's empty placeholder
    assert default_database() is None


def test_unreadable_settings_fall_back_to_reachable_database(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    bad = write_settings(tmp_path, "rekordbox7", tmp_path / "missing")
    bad.write_text("not xml", encoding="utf-8")
    database = tmp_path / "collection" / "master.db"
    database.parent.mkdir()
    database.touch()
    write_settings(tmp_path, "rekordbox6", database.parent)
    assert default_database() == database


def test_relative_and_environment_paths_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    database = tmp_path / "Pioneer" / "Music" / "master.db"
    database.parent.mkdir(parents=True)
    database.touch()
    settings = write_settings(tmp_path, "rekordbox7", Path("..") / "Music")
    assert default_database().resolve() == database
    monkeypatch.setenv("RBM_TEST_COLLECTION", str(database.parent))
    write_settings(tmp_path, "rekordbox7", "%RBM_TEST_COLLECTION%")
    assert settings.is_file() and default_database() == database
