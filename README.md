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
    Projects/
      ads_attribution/
        _index.md
        sessions/
          20260508-codex-fix-exporter-bug.md
        raw/
          codex/
            019e0544-7beb-7983-a458-de94206793f8.jsonl
          claude/
            fd7d3855-0b5d-482d-a008-0827ab6cd875.jsonl
```

Project folders use the short project name. When a checkout has a git remote, the exporter uses the repository name, for example `ads_attribution` from `luoli523/ads_attribution`. If no git remote is found, it falls back to the directory name. Session note filenames use `YYYYMMDD-[codex|claude]-[ascii-session-name].md`, where `YYYYMMDD` is the session's last updated date. Non-ASCII title text is dropped, with the session id prefix as a fallback.

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

By default, hooks automatically export the full conversation transcript at the end of each Codex or Claude Code turn. No manual save marker is required. Repeated hook runs rewrite the same session note with the latest full transcript; if the session's `YYYYMMDD` date changes, the note is renamed instead of duplicated. Add `#nosave` on its own line to skip saving a conversation. Manual `export`, `scan`, and `backfill` commands also export full transcripts directly.

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
  "archive_raw": true,
  "save_policy": "always",
  "save_triggers": [],
  "skip_triggers": ["#nosave"]
}
```

## Development

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

No third-party Python dependencies are required.
