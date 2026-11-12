# Calibration

No hand labels were added. No truth row was marked verified. Every `*_CALIBRATED` flag in `src/utilitydata/core/config.py` stays false.

`utilitydata calibrate sample` writes a seeded, unlabelled sample. `utilitydata calibrate score` reads `label`, `labelled_by`, `labelled_on`, and `note`. It refuses a row with no labeller and reports precision with a Wilson interval for each method. It does not change a flag.

A flag may be true only when `registry/calibration/measurements.csv` has a row for that flag with a labeller and a precision. The build checks that record. The score command never writes the flag.

Gas name-key precision is unmeasured. `GAS_NAME_KEYS_CALIBRATED` stays false, and the three name tiers stay in the code.
