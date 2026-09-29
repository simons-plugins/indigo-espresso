# Changelog

## 2026.0.6
- New **Start backflush** action and menu item: pump runs until 2 min after the last one count as one backflush, not shots.
- Removed the automatic backflush rule. It relied on how many pump runs the plug happened to show, which is chance (#3). Without the button, backflush cycles count as shots.
- Shots are recorded as soon as the pump stops (the confirmation wait existed only for the automatic rule).
- Against Simon's logged shots, 14-27 Sep: 24 of 24 found; the only false detections are the 26 Sep backflush runs, made before the button existed.

## 2026.0.5
- Fix: undecided pump runs (and the steam window after a shot) now survive a device or plugin restart. Saving a device's settings restarts it; on 29 Sep that lost a whole backflush.
- Bianca preset: pump + heater cut-off lowered from 1,480 to 1,470 W. A 29 Sep shot read only 1,476 W and was missed. Existing devices keep their values: press **Load preset values** to pick this up.

## 2026.0.4
- Tests: six more logged shots added to the reference list (19, 22, 23 and 26 Sep); 23 of 24 found, no false detections.

## 2026.0.3
- Tests: replay fixtures re-exported with correct local times (the first export was an hour late).
- Tests: detected shots are now checked against the shots Simon logged in Beanconqueror (17 of 18 found).

## 2026.0.2
- An espresso without milk is now recorded about 2 minutes after the shot (was 6).
- Fix: a pump run still in progress no longer lets earlier runs be decided as shots - a long backflush cycle could split a backflush into shots.

## 2026.0.1
- First release: status device, events and counters for a Lelit Bianca V3; unverified Lelit Elizabeth preset.
