# workouts/

Every workout the engine generates is saved here, filed by what it is **for**
(its intention), so the folder stays browsable as it grows. This folder's
contents are personal and are not tracked by git; only this file is.

```
workouts/
├── recovery/        active recovery, easy spins
├── endurance/       aerobic endurance, base, activation, easy days with touches
├── tempo/
├── sub_threshold/   sweet spot (power) and SubThreshold (heart rate)
├── threshold/
├── vo2max/
├── anaerobic/
├── neuromuscular/   sprints
└── catalog.sqlite   the engine's own memory of what it has generated
```

Subfolders are created the first time a workout of that kind is saved.

## File names

A single session:

```
2026-10-09_power_tempo_45min_382774b5.md
  date      mode zone  total  id
```

A progression gets one folder, with one numbered file per session:

```
tempo/2026-10-09_power_tempo_progression_prog_ab12cd34/session_01.md
```

The intention comes from the zone you asked for (`engine/storage.py`).

## Keeping them somewhere else

Set the environment variable `WORKOUT_ENGINE_WORKOUTS` to another folder and
the same structure is created there.
