# Garmin Training Insights

## First-time setup (when user says "set me up" or similar)

If there's no `.env` file or no `data/` with activities, run the full onboarding:

### 1. Python environment
```bash
# Find Python 3.12 (NOT 3.14 — pip hangs on 3.14)
py -3.12 --version || python3.12 --version || python3 --version || python --version
# Create venv with the best available Python 3.12
py -3.12 -m venv .venv || python3.12 -m venv .venv || python3 -m venv .venv || python -m venv .venv
# Install dependencies
.venv/Scripts/python.exe -m pip install -r requirements.txt  # Windows
# or: .venv/bin/python -m pip install -r requirements.txt    # macOS/Linux
```

### 2. Garmin credentials
Ask the user for their Garmin Connect email and password. Create `.env`:
```
GARMIN_EMAIL=<their email>
GARMIN_PASSWORD=<their password>
RUNNING_FTP=
CYCLING_FTP=
ANALYSIS_TIMEZONE=Europe/Prague
```

### 3. First login & data download
```bash
.venv/Scripts/python.exe src/ingestion/garmin_sync.py --test
```
If 2FA is needed, the user will need to enter the MFA code. Tell them:
"Check your phone for a verification code from Garmin and type it here."

If it hangs on 429 rate limit, wait 30-60 seconds and retry (the script has built-in retry).

After successful login, download data:
```bash
.venv/Scripts/python.exe src/ingestion/garmin_sync.py --last-month
.venv/Scripts/python.exe src/ingestion/garmin_sync.py --daily --last-month
```

### 4. Consolidate data
```bash
.venv/Scripts/python.exe src/analysis/consolidate.py --skip-records  # fast first run
```

### 5. Onboarding analysis
After consolidation, explore the data:
```python
import pandas as pd
act = pd.read_parquet('data/consolidated/activities.parquet')
daily = pd.read_parquet('data/consolidated/daily.parquet')
```

Detect:
- What sports does the user do? (`act['sport'].value_counts()`)
- Do they have power data on bike? (`act[act['sport']=='indoor_cycling']['avg_power'].notna().sum()`)
- Do they have Stryd? (`act['has_stryd'].sum()` if column exists)
- Do they have CORE sensor? (`act['has_core_sensor'].sum()` if column exists)

Estimate FTP:
- **Cycling**: Use MMP curves (mmp_5min, mmp_10min, mmp_20min) + 2-parameter CP model. FTP = 95% CP.
- **Running (Stryd)**: Use MMP curves from Stryd data. CP model from 5min, 10min, 20min. rFTP = 90% CP.
- **Running (no Stryd)**: Use pace @ HR analysis for threshold estimation.

IMPORTANT: Always ask the user if they have key workouts (tests, races, max efforts) that might not be in the default time window. Don't rely only on automatic MMP extraction.

Save FTP to `.env` and tell the user what you found.

## Regular usage

### Sync new data
```bash
.venv/Scripts/python.exe src/ingestion/garmin_sync.py --last-week
.venv/Scripts/python.exe src/ingestion/garmin_sync.py --daily --last-week
.venv/Scripts/python.exe src/analysis/consolidate.py --skip-records
```

Garmin tokens are in `data/garth_tokens/` — no 2FA needed after first login (tokens last weeks).

### Post-workout analysis
```bash
.venv/Scripts/python.exe src/analysis/post_workout.py                # last workout
.venv/Scripts/python.exe src/analysis/post_workout.py --last 3       # last 3
.venv/Scripts/python.exe src/analysis/post_workout.py --date 2026-03-22
```

After running the script, add context:
- Health data (HRV, sleep, stress from daily.parquet)
- Nutrition recommendations (calories burned, sodium needs based on duration/intensity)
- Comparison with similar past workouts
- Whether Z2 was actually Z2 (cardiac drift under 5% = good)

### Working with data
Always use parquet files, never re-parse FIT files:
```python
act = pd.read_parquet('data/consolidated/activities.parquet')     # 1 row per activity
laps = pd.read_parquet('data/consolidated/laps.parquet')          # 1 row per lap
recs = pd.read_parquet('data/consolidated/records_1s.parquet')    # per-second (large!)
daily = pd.read_parquet('data/consolidated/daily.parquet')        # daily health
```

For per-second analysis of specific workouts, parse FIT from zip:
```python
import zipfile, io
from fitparse import FitFile
with zipfile.ZipFile(f'data/activities/activity_{id}.zip') as z:
    fitfile = FitFile(io.BytesIO(z.read([n for n in z.namelist() if n.endswith('.fit')][0])))
```

## Key analytical capabilities

### FTP/CP Estimation
- 2-parameter CP model: P(t) = CP + W'/t
- Fit on 5min, 10min, 20min MMP data (avoid 1min — too anaerobic)
- Cycling FTP = 95% CP, Running rFTP = 90% CP
- Validate with HR response on threshold laps
- IMPORTANT: Stryd CP ≠ FTP. If user says "my Stryd CP is X", their training FTP is ~90% of X.

### Zone Analysis
- Cardiac drift on Z2 segments: under 5% = correct Z2, over 10% = too fast
- Compare HR @ same power over time = fitness trend
- Detect if user's Z2 is actually Z3 (common issue with wrong FTP)

### Workout Quality Assessment
- Interval power consistency (fade = too hard or fatigued)
- HR rise across intervals (high = near limit)
- Z2 cardiac drift (key metric for aerobic base building)
- Comparison with most recent similar workout

### Running Technique (Stryd)
- Form Power ratio: percentage of total power "wasted" on stabilization (elite: 20-25%, typical: 28-35%)
- Vertical Oscillation: increases with fatigue = losing efficiency
- Leg Spring Stiffness: higher = more elastic, efficient running
- Cadence trends under fatigue
- Ground Contact Time: increases with fatigue

### Sleep & Recovery
- HRV trends (correlate with performance)
- Deep sleep is more important than total sleep duration
- Body Battery correlation with next-day performance
- Detect illness early (HRV spike + high deep sleep + high REM = immune response)

### Nutrition (basic)
- Post-workout calorie/protein needs based on duration and intensity
- Sodium needs for heavy sweaters (estimate from duration, intensity, temperature)
- Carb intake timing around workouts

## Important notes
- Power sources differ: Stryd running power (200-330W) vs Garmin running power (300-430W) are NOT comparable
- For cross-period comparison when power source changed, use pace @ HR instead
- Always check `power_source` column in activities.parquet before comparing power data
- Communication style: practical, data-driven, no bullshit. Users want actionable insights, not academic papers.
