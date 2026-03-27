#!/usr/bin/env python3
"""
Data Consolidation Pipeline
Parsuje všechna surová data (JSON + FIT) do předpočítaných parquet souborů.

Výstup:
  data/consolidated/
    activities.parquet    - jedna řádka per aktivita (summary + Stryd metriky)
    laps.parquet          - jedna řádka per lap (čisté intervaly, warmup, cooldown)
    records_1s.parquet    - per-second data pro všechny aktivity
    daily.parquet         - denní health metriky (HRV, sleep, stress, BB, ...)

Spuštění:
    python src/analysis/consolidate.py           # vše
    python src/analysis/consolidate.py --skip-records  # bez per-second (rychlejší)
"""

import sys
import os
import json
import zipfile
import io
import argparse
from pathlib import Path
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np
from fitparse import FitFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ACTIVITIES_DIR = DATA_DIR / "activities"
DAILY_DIR = DATA_DIR / "daily"
OUT_DIR = DATA_DIR / "consolidated"
OUT_DIR.mkdir(exist_ok=True)


def parse_fit_file(zip_path: Path) -> tuple[list[dict], list[dict]]:
    """Parse FIT file from zip, return (laps, records)."""
    laps = []
    records = []

    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            fit_names = [n for n in z.namelist() if n.endswith('.fit')]
            if not fit_names:
                return laps, records
            fit_data = z.read(fit_names[0])
            fitfile = FitFile(io.BytesIO(fit_data))

            # Parse records (per-second)
            for rec in fitfile.get_messages('record'):
                fields = {f.name: f.value for f in rec.fields}
                records.append({
                    'timestamp': fields.get('timestamp'),
                    'heart_rate': fields.get('heart_rate'),
                    'power_native': fields.get('power'),
                    'power_stryd': fields.get('Power'),
                    'speed': fields.get('enhanced_speed'),
                    'distance': fields.get('distance'),
                    'altitude': fields.get('enhanced_altitude'),
                    'cadence': fields.get('cadence'),
                    'stance_time': fields.get('stance_time') or fields.get('Ground Time'),
                    'vertical_oscillation': fields.get('vertical_oscillation'),
                    'stance_time_balance': fields.get('stance_time_balance'),
                    'step_length': fields.get('step_length'),
                    'vertical_ratio': fields.get('vertical_ratio'),
                    'form_power': fields.get('Form Power'),
                    'leg_spring_stiffness': fields.get('Leg Spring Stiffness'),
                    'air_power': fields.get('Air Power'),
                    'impact_loading_rate': fields.get('Impact Loading Rate'),
                    'core_temperature': fields.get('core_temperature'),
                    'skin_temperature': fields.get('skin_temperature'),
                    'temperature': fields.get('temperature'),
                })

            # Parse laps
            for i, lap in enumerate(fitfile.get_messages('lap')):
                fields = {f.name: f.value for f in lap.fields}
                stryd_pwr = None
                for f in lap.fields:
                    if 'Power' in str(f.name) and f.value and f.value > 0:
                        stryd_pwr = f.value

                laps.append({
                    'lap_num': i + 1,
                    'start_time': fields.get('start_time') or fields.get('timestamp'),
                    'duration': fields.get('total_elapsed_time'),
                    'distance': fields.get('total_distance'),
                    'avg_hr': fields.get('avg_heart_rate'),
                    'max_hr': fields.get('max_heart_rate'),
                    'avg_speed': fields.get('enhanced_avg_speed'),
                    'avg_cadence': fields.get('avg_running_cadence') or fields.get('avg_cadence'),
                    'avg_power_native': fields.get('avg_power'),
                    'avg_power_stryd': stryd_pwr,
                    'lap_trigger': str(fields.get('lap_trigger', '')),
                    'intensity': str(fields.get('intensity', '')),
                })

    except Exception as e:
        pass

    return laps, records


def consolidate_activities(include_records: bool = True):
    """Build activities, laps, and optionally records tables."""
    all_activities = []
    all_laps = []
    all_records = []

    json_files = sorted(ACTIVITIES_DIR.glob('activity_*.json'))
    total = len(json_files)

    for idx, jf in enumerate(json_files):
        if idx % 20 == 0:
            print(f"  Activities: {idx}/{total}...")

        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)

        activity_id = data.get('activityId')
        s = data.get('summaryDTO', {})
        ts = s.get('startTimeLocal', '')
        sport = data.get('activityTypeDTO', {}).get('typeKey', '')

        speed = s.get('averageSpeed') or 0
        pace_minkm = (1000 / speed / 60) if speed > 0 else None

        activity = {
            'activity_id': activity_id,
            'date': ts[:10] if ts else None,
            'datetime': ts,
            'name': data.get('activityName', ''),
            'sport': sport,
            'duration_s': s.get('duration'),
            'distance_m': s.get('distance'),
            'avg_hr': s.get('averageHR'),
            'max_hr': s.get('maxHR'),
            'avg_power': s.get('averagePower'),
            'norm_power': s.get('normalizedPower'),
            'max_power_20min': s.get('maxPowerTwentyMinutes'),
            'ftp': s.get('functionalThresholdPower'),
            'tss': s.get('trainingStressScore'),
            'intensity_factor': s.get('intensityFactor'),
            'training_effect': s.get('trainingEffect'),
            'anaerobic_te': s.get('anaerobicTrainingEffect'),
            'avg_speed_ms': speed,
            'pace_minkm': pace_minkm,
            'avg_cadence': s.get('averageRunCadence') or s.get('averageBikeCadence'),
            'ground_contact_time': s.get('groundContactTime'),
            'vertical_oscillation': s.get('verticalOscillation'),
            'stride_length': s.get('strideLength'),
            'calories': s.get('calories'),
            'total_work_kj': s.get('totalWork'),
        }

        # Parse FIT data
        zip_path = jf.with_suffix('.zip')
        if zip_path.exists():
            laps, records = parse_fit_file(zip_path)

            # Per-second: compute extra metrics
            if records:
                powers = [r['power_stryd'] or r['power_native'] for r in records
                          if (r['power_stryd'] or r['power_native'])]
                hrs = [r['heart_rate'] for r in records if r['heart_rate']]
                gcts = [r['stance_time'] for r in records if r['stance_time'] and r['stance_time'] > 0]
                lsss = [r['leg_spring_stiffness'] for r in records if r['leg_spring_stiffness'] and r['leg_spring_stiffness'] > 0]
                temps = [r['core_temperature'] for r in records if r['core_temperature']]

                activity['fit_avg_power'] = np.mean(powers) if powers else None
                activity['fit_max_power'] = max(powers) if powers else None
                activity['fit_avg_hr'] = np.mean(hrs) if hrs else None
                activity['fit_avg_gct'] = np.mean(gcts) if gcts else None
                activity['fit_avg_lss'] = np.mean(lsss) if lsss else None
                activity['fit_avg_core_temp'] = np.mean(temps) if temps else None
                activity['has_stryd'] = any(r['power_stryd'] for r in records)
                activity['has_core_sensor'] = bool(temps)

                # Power source
                if any(r['power_stryd'] for r in records):
                    activity['power_source'] = 'stryd'
                elif any(r['power_native'] for r in records):
                    activity['power_source'] = 'garmin'
                else:
                    activity['power_source'] = None

                # MMP: max mean power for key durations
                if powers and len(powers) > 60:
                    pwr_arr = np.array([r['power_stryd'] or r['power_native'] or 0 for r in records], dtype=float)
                    for dur_name, dur_s in [('mmp_5s', 5), ('mmp_30s', 30), ('mmp_1min', 60),
                                            ('mmp_5min', 300), ('mmp_10min', 600), ('mmp_20min', 1200)]:
                        if len(pwr_arr) >= dur_s:
                            rolling = np.convolve(pwr_arr, np.ones(dur_s)/dur_s, mode='valid')
                            activity[dur_name] = float(np.max(rolling))
                        else:
                            activity[dur_name] = None

                # Cardiac drift: first half vs second half of steady efforts
                if hrs and len(hrs) > 120:
                    half = len(hrs) // 2
                    hr_first = np.mean(hrs[:half])
                    hr_second = np.mean(hrs[half:])
                    if hr_first > 0:
                        activity['cardiac_drift_pct'] = float((hr_second - hr_first) / hr_first * 100)

            # Laps: add activity context
            for lap in laps:
                lap['activity_id'] = activity_id
                lap['date'] = ts[:10] if ts else None
                lap['sport'] = sport
                lap['activity_name'] = data.get('activityName', '')
                # Compute pace from speed
                ls = lap.get('avg_speed') or 0
                lap['pace_minkm'] = (1000 / ls / 60) if ls > 0.3 else None
                # Best power field
                lap['power'] = lap.get('avg_power_stryd') or lap.get('avg_power_native')
            all_laps.extend(laps)

            # Records: tag with activity_id
            if include_records:
                for r in records:
                    r['activity_id'] = activity_id
                    r['sport'] = sport
                    r['power'] = r.get('power_stryd') or r.get('power_native')
                all_records.extend(records)

        all_activities.append(activity)

    # Save
    df_act = pd.DataFrame(all_activities)
    df_act.to_parquet(OUT_DIR / "activities.parquet", index=False)
    print(f"  activities.parquet: {len(df_act)} rows")

    df_laps = pd.DataFrame(all_laps)
    df_laps.to_parquet(OUT_DIR / "laps.parquet", index=False)
    print(f"  laps.parquet: {len(df_laps)} rows")

    if include_records and all_records:
        df_rec = pd.DataFrame(all_records)
        df_rec.to_parquet(OUT_DIR / "records_1s.parquet", index=False)
        print(f"  records_1s.parquet: {len(df_rec)} rows")

    return df_act


def consolidate_daily():
    """Build daily health metrics table."""
    all_daily = []

    for f in sorted(DAILY_DIR.glob('daily_*.json')):
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)

        date = data.get('date', f.stem.replace('daily_', ''))
        row = {'date': date}

        # Summary
        summary = data.get('summary', {})
        if isinstance(summary, dict):
            row['steps'] = summary.get('totalSteps')
            row['calories'] = summary.get('totalKilocalories')
            row['active_calories'] = summary.get('activeKilocalories')
            row['avg_stress'] = summary.get('averageStressLevel')
            row['max_stress'] = summary.get('maxStressLevel')
            row['bb_charged'] = summary.get('bodyBatteryChargedValue')
            row['bb_drained'] = summary.get('bodyBatteryDrainedValue')
            row['bb_high'] = summary.get('bodyBatteryMostRecentValue')
            row['intensity_minutes'] = summary.get('moderateIntensityMinutes', 0) or 0
            row['vigorous_minutes'] = summary.get('vigorousIntensityMinutes', 0) or 0

        # Sleep
        sleep = data.get('sleep', {})
        if isinstance(sleep, dict):
            ds = sleep.get('dailySleepDTO', {})
            if ds:
                row['sleep_seconds'] = ds.get('sleepTimeSeconds')
                row['sleep_hours'] = ds.get('sleepTimeSeconds', 0) / 3600 if ds.get('sleepTimeSeconds') else None
                score = ds.get('overallSleepScore')
                row['sleep_score'] = score.get('value') if isinstance(score, dict) else score
                row['deep_sleep_s'] = ds.get('deepSleepSeconds')
                row['light_sleep_s'] = ds.get('lightSleepSeconds')
                row['rem_sleep_s'] = ds.get('remSleepSeconds')
                row['awake_s'] = ds.get('awakeSleepSeconds')

        # HRV
        hrv = data.get('hrv', {})
        if isinstance(hrv, dict):
            hs = hrv.get('hrvSummary', {})
            if hs:
                row['hrv_weekly_avg'] = hs.get('weeklyAvg')
                row['hrv_last_night'] = hs.get('lastNightAvg')
                row['hrv_status'] = hs.get('status')
                row['hrv_baseline_low'] = hs.get('baselineLowUpper')
                row['hrv_baseline_high'] = hs.get('baselineBalancedUpper')

        # RHR
        rhr = data.get('rhr', {})
        if isinstance(rhr, dict):
            row['rhr'] = rhr.get('restingHeartRate')

        # Training readiness
        tr = data.get('training_readiness', {})
        if isinstance(tr, dict):
            row['training_readiness'] = tr.get('score') or tr.get('readinessScore')
            row['training_readiness_level'] = tr.get('level') or tr.get('readinessLevel')

        all_daily.append(row)

    df = pd.DataFrame(all_daily)
    df.to_parquet(OUT_DIR / "daily.parquet", index=False)
    print(f"  daily.parquet: {len(df)} rows")
    return df


def main():
    parser = argparse.ArgumentParser(description='Consolidate Garmin data')
    parser.add_argument('--skip-records', action='store_true',
                        help='Skip per-second records (much faster)')
    args = parser.parse_args()

    print("=== Consolidating Garmin data ===")
    print()

    print("Activities + Laps" + (" + Records" if not args.skip_records else "") + "...")
    consolidate_activities(include_records=not args.skip_records)
    print()

    print("Daily health data...")
    consolidate_daily()
    print()

    print("Done! Files in:", OUT_DIR)


if __name__ == "__main__":
    main()
