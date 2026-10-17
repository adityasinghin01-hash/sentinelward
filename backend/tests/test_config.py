"""Configuration validation and runtime controls."""
from pathlib import Path

import pytest
import yaml

from sw_api.config import BACKEND_DIR, ConfigError, Settings, load_users, load_ward


def ward_doc():
    return yaml.safe_load((BACKEND_DIR / "ward.yaml").read_text())


def write_ward(tmp_path, doc):
    path = tmp_path / "ward.yaml"
    path.write_text(yaml.safe_dump(doc))
    (tmp_path / "users.yaml").write_text((BACKEND_DIR / "users.yaml").read_text())
    return path


def test_demo_role_session_and_frontend_environment_controls():
    settings = Settings.from_env({"SW_DEMO_ROLE_LOGIN": "off", "SW_SESSION_TTL_S": "600",
                                  "SW_FRONTEND_DIST": "/tmp/ward-dist"})
    assert settings.demo_role_login is False
    assert settings.session_ttl_s == 600
    assert settings.frontend_dist == Path("/tmp/ward-dist")
    defaults = Settings.from_env({})
    assert defaults.demo_role_login is True
    assert defaults.use_memory_store is True
    assert defaults.frontend_dist == BACKEND_DIR.parent / "web" / "dist"


@pytest.mark.parametrize("env", [{"SW_DEMO_ROLE_LOGIN": "maybe"}, {"SW_SESSION_TTL_S": "0"},
                                  {"SW_SESSION_TTL_S": "nan"}])
def test_invalid_session_controls_rejected(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


@pytest.mark.parametrize("mutation", ["missing_bed", "wrong_bed", "wrong_preview", "duplicate_preview",
                                     "empty_initials", "unknown_nurse", "doctor_as_nurse"])
def test_invalid_ward_contract_rejected(tmp_path, mutation):
    doc = ward_doc()
    if mutation == "missing_bed":
        doc["beds"].pop()
    elif mutation == "wrong_bed":
        doc["beds"][-1].update(bed_id="B13", device_id="MON-13")
    elif mutation == "wrong_preview":
        doc["ward"]["preview_beds"] = ["B01", "B02", "B03", "B05"]
    elif mutation == "duplicate_preview":
        doc["ward"]["preview_beds"] = ["B01", "B02", "B03", "B03"]
    elif mutation == "empty_initials":
        doc["beds"][0]["patient"]["initials"] = "   "
    elif mutation == "unknown_nurse":
        doc["beds"][0]["nurse"] = "staff:nobody"
    else:
        doc["beds"][0]["nurse"] = "staff:dr_mehta"
    with pytest.raises(ConfigError):
        load_ward(write_ward(tmp_path, doc))


def test_distributed_ward_loads_with_explicit_users():
    users = load_users(BACKEND_DIR / "users.yaml")
    ward = load_ward(BACKEND_DIR / "ward.yaml", users)
    assert [bed.bed_id for bed in ward.beds] == [f"B{i:02}" for i in range(1, 13)]
    assert ward.preview_beds == ("B01", "B02", "B03", "B04")


def test_non_text_preview_id_is_configuration_error(tmp_path):
    doc = ward_doc()
    doc["ward"]["preview_beds"] = ["B01", None, "B03", "B04"]
    with pytest.raises(ConfigError):
        load_ward(write_ward(tmp_path, doc))
