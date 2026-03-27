# Garmin Training Insights

Your personal AI training coach. Connect Garmin, ask anything about your training.

## What it does

- Downloads your Garmin Connect data (activities, sleep, HRV, stress, Body Battery)
- Parses FIT files for per-second power, HR, cadence, running dynamics (Stryd, CORE sensor)
- Estimates FTP/CP without formal tests
- Analyzes every workout: zones, cardiac drift, interval quality, comparison with past
- Tracks long-term progress and identifies bottlenecks
- Gives nutrition/hydration recommendations around workouts

## What you need

- **Python 3.12** (not 3.14 — pip has issues on 3.14)
- **AI coding assistant** — any of these:
  - [Claude Code](https://claude.ai/code)
  - [OpenAI Codex](https://openai.com/codex)
  - [Cursor](https://cursor.com)
  - Any AI tool that reads project instructions from markdown

## Setup — 3 steps

1. **Clone this repo**
2. **Open the folder in your AI coding assistant**
3. **Type: "Set me up"**

The AI will do everything else — install dependencies, connect your Garmin account, download data, analyze your training, and estimate your zones.

Works with Claude Code (`CLAUDE.md`), OpenAI Codex (`AGENTS.md`), and any tool that reads project-level instructions.

## What you can ask

- "How did my last workout go?"
- "What's my FTP?"
- "Why do my easy runs feel hard?"
- "Am I overtraining?"
- "How's my sleep affecting my performance?"
- "What should I eat after this workout?"
- "Show me my running technique trends"
- "Compare my last month to the month before"

## Supported sensors

Works with any Garmin watch. Extra insights if you have:
- **Power meter** (cycling) — FTP/CP estimation, zone analysis
- **Stryd** (running power) — running FTP, form power, leg spring stiffness, technique analysis
- **CORE sensor** — body temperature, heat stress analysis
- **Libre CGM** — glucose during workouts (coming soon)

## Sample data

Want to try it without connecting Garmin? Copy `sample_data/` contents to `data/` and ask your AI to analyze it.

## License

MIT — free to use, modify, and share.
