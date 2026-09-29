import pytest

import profiles


def test_bianca_preset_matches_measured_values():
    th = profiles.preset_thresholds("biancaV3")
    assert th["pumpMinW"] == 150 and th["pumpMaxW"] == 350
    assert th["steamMinW"] == 1150 and th["steamMaxW"] == 1360
    assert th["brewMinW"] == 1360 and th["brewMaxW"] == 1470
    assert th["pumpHeaterMinW"] == 1470
    assert th["ecoTimeoutMin"] == 30 and th["idleSilenceMin"] == 8
    assert set(th) == set(profiles.THRESHOLD_KEYS)


def test_elizabeth_is_unverified_and_complete():
    assert profiles.PRESETS["elizabeth"]["verified"] is False
    assert set(profiles.preset_thresholds("elizabeth")) == set(profiles.THRESHOLD_KEYS)


def test_menu_lists_presets_and_custom():
    keys = [k for k, _ in profiles.preset_menu()]
    assert keys == ["biancaV3", "elizabeth", "custom"]


def test_custom_has_no_thresholds():
    with pytest.raises(KeyError):
        profiles.preset_thresholds("custom")


def test_thresholds_from_props_parses_strings():
    props = {k: str(v) for k, v in profiles.preset_thresholds("biancaV3").items()}
    assert profiles.thresholds_from_props(props)["pumpMinW"] == 150.0


def test_thresholds_from_props_names_bad_keys():
    props = {k: "1" for k in profiles.THRESHOLD_KEYS}
    props["pumpMinW"] = "abc"
    del props["tankLowPct"]
    with pytest.raises(ValueError) as exc:
        profiles.thresholds_from_props(props)
    assert "pumpMinW" in str(exc.value) and "tankLowPct" in str(exc.value)


def test_validate_rejects_min_above_max_and_bad_pct():
    props = {k: str(v) for k, v in profiles.preset_thresholds("biancaV3").items()}
    props["pumpMinW"] = "400"
    props["tankLowPct"] = "150"
    errors = profiles.validate_props(props)
    assert set(errors) == {"pumpMinW", "tankLowPct"}


def test_validate_accepts_both_presets():
    for key in ("biancaV3", "elizabeth"):
        props = {k: str(v) for k, v in profiles.preset_thresholds(key).items()}
        assert profiles.validate_props(props) == {}
