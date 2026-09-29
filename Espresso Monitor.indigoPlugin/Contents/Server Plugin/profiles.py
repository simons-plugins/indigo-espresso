"""Machine presets and threshold parsing. No Indigo import."""

THRESHOLD_KEYS = (
    "idleMaxW", "pumpMinW", "pumpMaxW", "steamMinW", "steamMaxW", "brewMinW", "brewMaxW",
    "pumpHeaterMinW", "heaterMinW", "ecoTimeoutMin", "heatSilenceMin", "idleSilenceMin",
    "noDrawMin", "tankLowPct",
)

PRESETS = {
    "biancaV3": {
        "label": "Lelit Bianca V3 (measured)",
        "verified": True,
        # Measured 2026-09 on an IKEA GRILLPLATS plug: pump ~230 W, steam heater
        # ~1.25-1.33 kW, brew heater ~1.37-1.46 kW, pump + brew heater ~1.48-1.69 kW.
        # The levels drift with mains voltage and element temperature: on 29 Sep a shot's
        # pump + heater read only 1,476 W. 1,470 is the lowest cut-off with no false shots
        # over 14-27 Sep (1,460 gave one); see issue #2 for learning the levels instead.
        "thresholds": {
            "idleMaxW": 20, "pumpMinW": 150, "pumpMaxW": 350, "steamMinW": 1150, "steamMaxW": 1360,
            "brewMinW": 1360, "brewMaxW": 1470, "pumpHeaterMinW": 1470, "heaterMinW": 1000,
            "ecoTimeoutMin": 30, "heatSilenceMin": 2, "idleSilenceMin": 8, "noDrawMin": 3, "tankLowPct": 85,
        },
    },
    "elizabeth": {
        "label": "Lelit Elizabeth (unverified)",
        "verified": False,
        # From published specs, not measured: vibratory pump (tens of watts),
        # ~800 W brew and ~1.2 kW steam heaters. Pump + heater can't be told from
        # heater alone, so pumpHeaterMinW is set out of reach and shots are found
        # from pump-alone readings only. Capture a session with raw logging on.
        "thresholds": {
            "idleMaxW": 20, "pumpMinW": 30, "pumpMaxW": 120, "steamMinW": 1000, "steamMaxW": 1300,
            "brewMinW": 650, "brewMaxW": 950, "pumpHeaterMinW": 99999, "heaterMinW": 600,
            "ecoTimeoutMin": 30, "heatSilenceMin": 2, "idleSilenceMin": 8, "noDrawMin": 3, "tankLowPct": 85,
        },
    },
}

_BANDS = (("pumpMinW", "pumpMaxW"), ("steamMinW", "steamMaxW"), ("brewMinW", "brewMaxW"))


def preset_menu():
    return [(key, p["label"]) for key, p in PRESETS.items()] + [("custom", "Custom")]


def preset_thresholds(key):
    return {k: float(v) for k, v in PRESETS[key]["thresholds"].items()}


def thresholds_from_props(props):
    out, bad = {}, []
    for key in THRESHOLD_KEYS:
        try:
            out[key] = float(props[key])
        except (KeyError, TypeError, ValueError):
            bad.append(key)
    if bad:
        raise ValueError("missing or non-numeric: " + ", ".join(bad))
    return out


def validate_props(props):
    errors = {}
    values = {}
    for key in THRESHOLD_KEYS:
        try:
            values[key] = float(props.get(key, ""))
            if values[key] < 0:
                errors[key] = "Must be zero or more"
        except (TypeError, ValueError):
            errors[key] = "Enter a number"
    for lo, hi in _BANDS:
        if lo in values and hi in values and values[lo] >= values[hi]:
            errors[lo] = "Must be below " + hi
    if "tankLowPct" in values and not 1 <= values["tankLowPct"] <= 100:
        errors["tankLowPct"] = "Enter 1-100"
    return errors
