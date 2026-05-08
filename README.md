# ai-convo-exporter

English | [简体中文](README.zh-CN.md)

Export Codex and Claude Code conversations into an Obsidian vault, grouped by project.

The exporter keeps two copies of each conversation:

- A readable Markdown note for Obsidian search, tags, links, and Dataview.
- The original JSONL transcript under `raw/`, so notes can be regenerated later.

## Layout

```text
Obsidian Vault/
  AI Conversations/
    Projects/
      luoli523__ads-attribution/
        _index.md
        sessions/
          2026-05-08 0947 codex 019e0544 save-chat.md
        raw/
          codex/
            019e0544-7beb-7983-a458-de94206793f8.jsonl
          claude/
            fd7d3855-0b5d-482d-a008-0827ab6cd875.jsonl
```

Project folders are stable across machines. When a checkout has a git remote, the exporter uses the remote path, for example `luoli523/ads_attribution`, and converts it to an Obsidian-safe folder slug such as `luoli523__ads-attribution`. If no git remote is found, it falls back to the directory name.

## Install

From a fresh checkout:

```bash
./install.sh
```

With an explicit vault:

```bash
./install.sh --vault "$HOME/Documents/Obsidian Vault"
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
- Enables Codex hooks in `~/.codex/config.toml`.

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
  "vault_dir": "~/Documents/Obsidian Vault",
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
