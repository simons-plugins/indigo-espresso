# Changelog

## 2026.1.1
- New **Mark tank refilled after running empty** action and menu item: use it when the tank ran dry but the plugin never noticed (keep-warm power can mask it). It learns this tankful, then refills. The existing mark-refilled action keeps its id but is now named **Mark tank topped up (no learning)**.

## 2026.1.0
- Fix: isolated pump-band readings between keep-warm heater bursts no longer count as water. On real Bianca data (3-7 Oct), these blips were ~80% of the counted pump time (~1,357 of 1,689 s); real shots and flushes were ~300 s. Water is now only credited for a run of pump readings with nothing idle in between.
- New **Shots since refill** counter, alongside pump seconds since refill.
- The event log now says how many shots and pump-seconds a tank lasted when it runs dry.
- The learned tank size is cleared once (it was learned under the old, inflated count). If the tank was already part-used at the upgrade, that first run-dry isn't learned either (it would still carry the inflated count) - the one after is.

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
