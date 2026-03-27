# Sample Data

Anonymized training data for demo purposes. To use:

1. Copy `activities/` and `daily/` into `data/`
2. Run consolidation: `.venv/Scripts/python.exe src/analysis/consolidate.py --skip-records`
3. Ask Claude to analyze it

Contains:
- 5 activities (easy ride, threshold ride, easy run, threshold run, intervals)
- 7 days of daily health data (sleep, HRV, stress, Body Battery)
