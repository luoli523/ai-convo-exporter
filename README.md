# ai-convo-exporter

English | [简体中文](README.zh-CN.md)

Export Codex and Claude Code conversations into an Obsidian vault, grouped by project.

The exporter keeps two copies of each conversation:

- A readable Markdown note for Obsidian search, tags, links, and Dataview.
- The original JSONL transcript under `raw/`, so notes can be regenerated later.

## Layout

```text
~/Documents/obsidian/
  AI Conversations/
    Daily/
      2026-05-08.md                              # daily roll-up (one line per session)
    Projects/
      ads_attribution/
        _index.md
        sessions/
          20260508-codex-保存对话.md            # CJK / unicode preserved
        raw/
          codex/
            019e0544-7beb-7983-a458-de94206793f8.jsonl
          claude/
            fd7d3855-0b5d-482d-a008-0827ab6cd875.jsonl
```

Project folders use the short project name. When a checkout has a git remote, the exporter uses the repository name, for example `ads_attribution` from `luoli523/ads_attribution`. If no git remote is found, it falls back to the directory name. Session note filenames use `YYYYMMDD-[codex|claude]-<title-slug>.md`, where the slug preserves CJK / unicode word characters and only normalizes punctuation and whitespace.

## What's in a session note

Each session note has rich frontmatter that Obsidian's Dataview can query:

```yaml
type: ai-conversation
provider: claude
session_id: 5a7c7cb2-...
project: ai-convo-exporter
project_slug: ai-convo-exporter
created: 2026-05-09T15:25:48+08:00
updated: 2026-05-09T18:35:15+08:00
cwd: /Users/me/work/ai-convo-exporter
git_repo: https://github.com/luoli523/ai-convo-exporter.git
git_branch: feat/enrich-markdown
machine: my-laptop
raw_transcript: ../raw/claude/5a7c7cb2-....jsonl
tool_call_count: 171
tools_used: [Bash, Edit, Read, TaskCreate, ToolSearch]
related_files: [src/ai_convo_exporter/cli.py, tests/test_exporter.py, README.md]
related_sessions: ["[[20260507-claude-vault-detection]]"]
decision_count: 11
tags: [ai/conversation, provider/claude, project/ai-convo-exporter]
```

The body opens with a TL;DR callout (topic, turn counts, files touched, decisions flagged), then the conversation. Assistant messages whose content is purely operational (e.g. running tools, narrating file edits) are wrapped in collapsed `> [!action]-` callouts so they don't dominate re-reading. Messages containing decision-indicator phrases ("我建议", "decision:", "let's go with", etc.) get a `> [!decision]+` callout marker.

The Daily/ note is updated on every export with one [[wiki-link]] line per session for that day, so Obsidian's Daily Notes / Periodic Notes workflows can surface AI work alongside other daily notes.

## Install

From a fresh checkout:

```bash
./install.sh
```

With an explicit vault:

```bash
./install.sh --vault "$HOME/Documents/obsidian"
```

Install and import historical local transcripts:

```bash
./install.sh --backfill
```

Dry-run without writing config:

```bash
./install.sh --dry-run
```

The installer:

- Creates `~/.config/ai-convo-exporter/config.json`.
- Installs a wrapper at `~/.local/bin/ai-convo-exporter`.
- Adds a Claude Code `Stop` hook to `~/.claude/settings.json`.
- Adds a Codex `Stop` hook to `~/.codex/hooks.json`.
- Enables Codex hooks with `[features] hooks = true` in `~/.codex/config.toml`.
- Adds the Obsidian vault to Codex `sandbox_workspace_write.writable_roots` so the hook can write notes while Codex runs in workspace-write mode.

Repeat installs are idempotent. The installer updates the same hook entries instead of appending duplicates.

## Commands

```bash
ai-convo-exporter hook --provider codex
ai-convo-exporter hook --provider claude
ai-convo-exporter export ~/.codex/sessions/.../rollout.jsonl --provider codex
ai-convo-exporter scan
ai-convo-exporter backfill
ai-convo-exporter doctor
```

## Configuration

Config file:

```text
~/.config/ai-convo-exporter/config.json
```

Environment overrides:

- `AI_CONVO_VAULT`: Obsidian vault path.
- `AI_CONVO_CONFIG`: Config file path.
- `AI_CONVO_TIMEZONE`: Installer default timezone.

Default config:

```json
{
  "vault_dir": "~/Documents/obsidian",
  "conversations_dir": "AI Conversations",
  "timezone": "Asia/Singapore",
  "machine": "hostname",
  "archive_raw": true
}
```

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

No third-party Python dependencies are required.
