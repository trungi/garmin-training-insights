#!/usr/bin/env python3
"""
Post-Workout Analysis
Analyzuje poslední trénink(y) a dává okamžitý feedback.

Spuštění:
    python src/analysis/post_workout.py                # poslední trénink
    python src/analysis/post_workout.py --last 3       # poslední 3
    python src/analysis/post_workout.py --date 2026-03-22  # konkrétní den
"""

import sys
import argparse
import json
import zipfile
import io
from pathlib import Path
from datetime import datetime, timedelta

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np
from fitparse import FitFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Load FTP from config (.env)
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from config import RUNNING_FTP as _RFTP, CYCLING_FTP as _CFTP
RUNNING_FTP = _RFTP or 250  # fallback if not set
CYCLING_FTP = _CFTP or 200  # fallback if not set

RUNNING_ZONES = {
    'Z1': (0, 0.76),
    'Z2': (0.76, 0.86),
    'Z3': (0.86, 0.96),
    'Z4': (0.96, 1.04),
    'Z5': (1.04, 1.12),
    'Z6': (1.12, 99),
}

CYCLING_ZONES = {
    'Z1': (0, 0.72),
    'Z2': (0.72, 0.87),
    'Z3': (0.87, 0.96),
    'Z4': (0.96, 1.05),
    'Z5': (1.05, 1.20),
    'Z6': (1.20, 99),
}


def get_zone(power, ftp, zones):
    """Return zone name for given power."""
    pct = power / ftp if ftp > 0 else 0
    for name, (low, high) in zones.items():
        if low <= pct < high:
            return name
    return 'Z6+'


def parse_fit_records(zip_path):
    """Parse per-second records from FIT file."""
    records = []
    laps = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            fit_names = [n for n in z.namelist() if n.endswith('.fit')]
            if not fit_names:
                return records, laps
            fitfile = FitFile(io.BytesIO(z.read(fit_names[0])))

            for rec in fitfile.get_messages('record'):
                fields = {f.name: f.value for f in rec.fields}
                records.append({
                    'timestamp': fields.get('timestamp'),
                    'hr': fields.get('heart_rate'),
                    'power': fields.get('Power') or fields.get('power'),
                    'speed': fields.get('enhanced_speed'),
                    'cadence': fields.get('cadence'),
                    'gct': fields.get('stance_time') or fields.get('Ground Time'),
                    'lss': fields.get('Leg Spring Stiffness'),
                    'vo': fields.get('vertical_oscillation'),
                })

            for i, lap in enumerate(fitfile.get_messages('lap')):
                fields = {f.name: f.value for f in lap.fields}
                stryd_pwr = None
                for f in lap.fields:
                    if 'Power' in str(f.name) and f.value and f.value > 0:
                        stryd_pwr = f.value
                laps.append({
                    'lap_num': i + 1,
                    'duration': fields.get('total_elapsed_time'),
                    'avg_hr': fields.get('avg_heart_rate'),
                    'max_hr': fields.get('max_heart_rate'),
                    'avg_speed': fields.get('enhanced_avg_speed'),
                    'power': stryd_pwr or fields.get('avg_power'),
                })
    except Exception:
        pass
    return records, laps


def analyze_cardiac_drift(records, power_range=None):
    """Calculate cardiac drift for records in given power range."""
    if power_range:
        filtered = [r for r in records if r['power'] and r['hr']
                     and power_range[0] <= r['power'] <= power_range[1]]
    else:
        filtered = [r for r in records if r['hr'] and r['power'] and r['power'] > 50]

    if len(filtered) < 120:
        return None, None, None

    half = len(filtered) // 2
    hr_first = np.mean([r['hr'] for r in filtered[:half]])
    hr_second = np.mean([r['hr'] for r in filtered[half:]])
    pwr_first = np.mean([r['power'] for r in filtered[:half]])
    pwr_second = np.mean([r['power'] for r in filtered[half:]])

    drift = (hr_second - hr_first) / hr_first * 100 if hr_first > 0 else 0
    return drift, (pwr_first, hr_first), (pwr_second, hr_second)


def find_similar_past(act_df, sport, workout_type, current_date, max_lookback=90):
    """Find most recent similar workout for comparison."""
    cutoff = (pd.to_datetime(current_date) - timedelta(days=max_lookback)).strftime('%Y-%m-%d')
    similar = act_df[
        (act_df['sport'] == sport) &
        (act_df['date'] >= cutoff) &
        (act_df['date'] < current_date)
    ].copy()

    if workout_type and len(similar) > 0:
        similar = similar[similar['name'].str.contains(workout_type, case=False, na=False)]

    if len(similar) > 0:
        return similar.iloc[-1]
    return None


def classify_workout(name):
    """Classify workout type from name."""
    n = str(name).lower()
    if any(x in n for x in ['easy', 'recovery']):
        return 'easy', 'Easy Run'
    elif any(x in n for x in ['threshold', 'cruise', 'tempo', 'marathon repeat']):
        return 'threshold', 'Threshold'
    elif any(x in n for x in ['interval', 'mav', 'shuttle', 'fartlek', 'decreasing']):
        return 'intensity', 'Intervals/VO2'
    elif 'transition' in n or 'off-the-bike' in n:
        return 'brick', 'Brick Run'
    elif any(x in n for x in ['step up', 'over under', 'power builder']):
        return 'threshold', 'Threshold'
    elif 'easy ride' in n:
        return 'easy', 'Easy Ride'
    elif '30-30' in n or '30-90' in n:
        return 'intensity', 'Intervals/VO2'
    else:
        return 'other', 'Other'


def analyze_workout(activity_json, act_df, daily_df):
    """Full analysis of a single workout."""
    with open(activity_json, 'r', encoding='utf-8') as f:
        data = json.load(f)

    s = data.get('summaryDTO', {})
    sport = data.get('activityTypeDTO', {}).get('typeKey', '')
    name = data.get('activityName', '')
    date = (s.get('startTimeLocal', '') or '')[:10]
    duration = s.get('duration', 0) or 0
    distance = s.get('distance', 0) or 0

    wtype, wtype_label = classify_workout(name)
    is_run = sport == 'running'
    is_bike = sport in ('indoor_cycling', 'road_biking')
    ftp = RUNNING_FTP if is_run else CYCLING_FTP
    zones = RUNNING_ZONES if is_run else CYCLING_ZONES

    result = {
        'name': name,
        'date': date,
        'sport': sport,
        'type': wtype_label,
        'duration_min': duration / 60,
        'distance_km': distance / 1000,
        'avg_hr': s.get('averageHR'),
        'max_hr': s.get('maxHR'),
        'training_effect': s.get('trainingEffect'),
    }

    # Parse FIT data
    zip_path = activity_json.with_suffix('.zip')
    records, laps = [], []
    if zip_path.exists():
        records, laps = parse_fit_records(zip_path)

    # === LAP ANALYSIS ===
    if laps:
        work_laps = []
        rest_laps = []
        for lap in laps:
            if not lap.get('power') or not lap.get('duration'):
                continue
            zone = get_zone(lap['power'], ftp, zones)
            lap['zone'] = zone
            if lap['duration'] >= 120 and lap['power'] > ftp * 0.9:
                work_laps.append(lap)
            elif lap['duration'] >= 60 and lap['power'] < ftp * 0.85:
                rest_laps.append(lap)

        result['work_laps'] = work_laps
        result['rest_laps'] = rest_laps

        if work_laps:
            powers = [l['power'] for l in work_laps]
            hrs = [l['avg_hr'] for l in work_laps if l.get('avg_hr')]
            result['work_avg_power'] = np.mean(powers)
            result['work_power_fade'] = (powers[-1] - powers[0]) / powers[0] * 100 if len(powers) > 1 else 0
            result['work_avg_hr'] = np.mean(hrs) if hrs else None
            result['work_hr_rise'] = hrs[-1] - hrs[0] if len(hrs) > 1 else 0

    # === CARDIAC DRIFT (Z2 segments) ===
    if records and is_run:
        z2_range = (ftp * 0.72, ftp * 0.90)
        drift, first, second = analyze_cardiac_drift(records, z2_range)
        if drift is not None:
            result['z2_cardiac_drift'] = drift
            result['z2_first_half'] = first
            result['z2_second_half'] = second

    # === OVERALL CARDIAC DRIFT ===
    if records:
        drift_all, first, second = analyze_cardiac_drift(records)
        if drift_all is not None:
            result['overall_drift'] = drift_all

    # === COMPARISON WITH SIMILAR PAST WORKOUT ===
    if act_df is not None and len(act_df) > 0:
        search_term = None
        for keyword in ['Threshold Repeats', 'Threshold & Hold', 'Intervals', 'Easy Run',
                        'Fartleks', 'MAV Shuttles', 'Step Ups', 'Easy Ride', 'Cruise']:
            if keyword.lower() in name.lower():
                search_term = keyword
                break

        prev = find_similar_past(act_df, sport, search_term, date)
        if prev is not None:
            result['prev_date'] = prev['date']
            result['prev_name'] = prev.get('name', '')
            result['prev_avg_hr'] = prev.get('avg_hr')
            result['prev_pace'] = prev.get('pace_minkm')

    # === HEALTH CONTEXT ===
    if daily_df is not None and len(daily_df) > 0:
        yesterday = (pd.to_datetime(date) - timedelta(days=1)).strftime('%Y-%m-%d')
        day_data = daily_df[daily_df['date'] == yesterday]
        if len(day_data) > 0:
            d = day_data.iloc[0]
            result['yesterday_hrv'] = d.get('hrv_weekly_avg')
            result['yesterday_sleep'] = d.get('sleep_hours')
            result['yesterday_stress'] = d.get('avg_stress')

    return result


def format_report(result):
    """Format analysis result into readable report."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"{result['name']}")
    lines.append(f"{result['date']} | {result['type']} | {result['duration_min']:.0f}min | {result['distance_km']:.1f}km")
    lines.append(f"{'='*60}")
    lines.append("")

    # Health context
    hrv = result.get('yesterday_hrv')
    sleep = result.get('yesterday_sleep')
    stress = result.get('yesterday_stress')
    if any(x is not None for x in [hrv, sleep, stress]):
        ctx_parts = []
        if hrv is not None:
            ctx_parts.append(f"HRV={hrv:.0f}")
        if sleep is not None:
            ctx_parts.append(f"sleep={sleep:.1f}h")
        if stress is not None:
            ctx_parts.append(f"stress={stress:.0f}")
        lines.append(f"Health (den pred): {', '.join(ctx_parts)}")
        lines.append("")

    # HR summary
    avg_hr = result.get('avg_hr')
    max_hr = result.get('max_hr')
    te = result.get('training_effect')
    if avg_hr:
        hr_line = f"HR: avg={avg_hr:.0f} max={max_hr:.0f}" if max_hr else f"HR: avg={avg_hr:.0f}"
        if te:
            hr_line += f" | Training Effect: {te:.1f}"
        lines.append(hr_line)
        lines.append("")

    # Work laps
    work_laps = result.get('work_laps', [])
    if work_laps:
        lines.append("INTERVALY:")
        for i, lap in enumerate(work_laps):
            dur = lap['duration'] / 60
            zone = lap.get('zone', '?')
            hr = f"HR {lap['avg_hr']:.0f}" if lap.get('avg_hr') else ""
            lines.append(f"  {i+1}. {dur:.1f}min @ {lap['power']:.0f}W ({zone}) {hr}")

        avg_pwr = result.get('work_avg_power')
        fade = result.get('work_power_fade', 0)
        hr_rise = result.get('work_hr_rise', 0)
        lines.append("")

        if abs(fade) < 3:
            lines.append(f"  Power: konstantni ({avg_pwr:.0f}W avg) = dobre kalibrované")
        elif fade < -5:
            lines.append(f"  Power: padal {fade:+.0f}% = moc tvrdý start nebo unavený")
        else:
            lines.append(f"  Power: stoupal {fade:+.0f}% = konzervativni start (ok)")

        if hr_rise > 8:
            lines.append(f"  HR: +{hr_rise:.0f} BPM pres intervaly = blizko limitu")
        elif hr_rise > 4:
            lines.append(f"  HR: +{hr_rise:.0f} BPM = normalni drift")
        else:
            lines.append(f"  HR: stabilni (+{hr_rise:.0f} BPM) = v pohode")
        lines.append("")

    # Z2 cardiac drift
    z2_drift = result.get('z2_cardiac_drift')
    if z2_drift is not None:
        first = result.get('z2_first_half', (0, 0))
        second = result.get('z2_second_half', (0, 0))
        lines.append("Z2 CARDIAC DRIFT:")
        lines.append(f"  1. pulka: {first[0]:.0f}W @ HR {first[1]:.0f}")
        lines.append(f"  2. pulka: {second[0]:.0f}W @ HR {second[1]:.0f}")

        if abs(z2_drift) < 3:
            lines.append(f"  Drift: {z2_drift:+.1f}% = VYBORNE, tohle je spravna Z2")
        elif abs(z2_drift) < 5:
            lines.append(f"  Drift: {z2_drift:+.1f}% = OK, horni hranice Z2")
        elif abs(z2_drift) < 10:
            lines.append(f"  Drift: {z2_drift:+.1f}% = MOC RYCHLE, tohle neni Z2!")
        else:
            lines.append(f"  Drift: {z2_drift:+.1f}% = DALEKO NAD Z2, zpomal!")
        lines.append("")

    # Comparison
    prev_date = result.get('prev_date')
    if prev_date:
        lines.append("VS PREDCHOZI:")
        prev_hr = result.get('prev_avg_hr')
        curr_hr = result.get('avg_hr')
        if prev_hr and curr_hr:
            hr_diff = curr_hr - prev_hr
            better = "LEPSI (nizsi HR)" if hr_diff < -2 else "HORSI (vyssi HR)" if hr_diff > 2 else "STEJNE"
            lines.append(f"  {prev_date}: HR {prev_hr:.0f} -> dnes: HR {curr_hr:.0f} ({hr_diff:+.0f}) = {better}")
        lines.append("")

    # Overall verdict
    lines.append("VERDICT:")
    verdicts = []

    if work_laps:
        fade = result.get('work_power_fade', 0)
        if abs(fade) < 5:
            verdicts.append("Intervaly: kvalitni stimulus, power stabilni")
        else:
            verdicts.append(f"Intervaly: power fade {fade:+.0f}%, mozna prilis ambiciozni")

    if z2_drift is not None:
        if abs(z2_drift) < 5:
            verdicts.append("Z2: spravna intenzita, buduje aerobni base")
        elif abs(z2_drift) < 10:
            verdicts.append("Z2: trochu rychle, zvaž snizit power o 10-15W")
        else:
            verdicts.append("Z2: MOC RYCHLE — tohle NIC nebuduje, jen unavi")

    if not verdicts:
        verdicts.append(f"Trenink dokoncen, TE={result.get('training_effect', '?')}")

    for v in verdicts:
        lines.append(f"  {v}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Post-workout analysis')
    parser.add_argument('--last', type=int, default=1, help='Analyze last N workouts')
    parser.add_argument('--date', type=str, help='Analyze specific date')
    parser.add_argument('--all-today', action='store_true', help='All workouts today')
    args = parser.parse_args()

    # Load consolidated data for comparison
    act_path = DATA_DIR / "consolidated" / "activities.parquet"
    daily_path = DATA_DIR / "consolidated" / "daily.parquet"
    act_df = pd.read_parquet(act_path) if act_path.exists() else pd.DataFrame()
    daily_df = pd.read_parquet(daily_path) if daily_path.exists() else pd.DataFrame()

    # Find target activities
    all_jsons = sorted(DATA_DIR.glob("activities/activity_*.json"))

    # Load and sort by date
    activities = []
    for jf in all_jsons:
        with open(jf, 'r', encoding='utf-8') as f:
            data = json.load(f)
        s = data.get('summaryDTO', {})
        ts = s.get('startTimeLocal', '')
        sport = data.get('activityTypeDTO', {}).get('typeKey', '')
        if sport in ('walking', 'breathwork', 'yoga'):
            continue
        activities.append((ts, jf))

    activities.sort(key=lambda x: x[0], reverse=True)

    # Filter
    if args.date:
        targets = [(ts, jf) for ts, jf in activities if args.date in ts]
    else:
        targets = activities[:args.last]

    if not targets:
        print("Zadne treninky nenalezeny.")
        return

    for ts, jf in reversed(targets):
        result = analyze_workout(jf, act_df, daily_df)
        report = format_report(result)
        print(report)
        print()


if __name__ == "__main__":
    main()
