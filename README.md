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
          20260508-codex-save-chat.md
        raw/
          codex/
            019e0544-7beb-7983-a458-de94206793f8.jsonl
          claude/
            fd7d3855-0b5d-482d-a008-0827ab6cd875.jsonl
```

Project folders use the short project name. When a checkout has a git remote, the exporter uses the repository name, for example `ads_attribution` from `luoli523/ads_attribution`. If no git remote is found, it falls back to the directory name. Session note filenames use `YYYYMMDD-[codex|claude]-[ascii-session-name].md`, where `YYYYMMDD` is the session's last updated date. Non-ASCII title text is dropped, with the session id prefix as a fallback.

## Install

### Recommended: pipx (no clone needed)

```bash
pipx install git+https://github.com/luoli523/ai-convo-exporter
ai-convo-exporter setup
```

`pipx` puts `ai-convo-exporter` on your PATH in an isolated venv. `setup`
detects your Obsidian vault, writes `~/.config/ai-convo-exporter/config.json`,
and installs Stop hooks for both Codex and Claude Code.

To remove later: `pipx uninstall ai-convo-exporter`.

### Alternative: pip --user

```bash
pip install --user git+https://github.com/luoli523/ai-convo-exporter
ai-convo-exporter setup
```

(On Homebrew Python you may hit PEP 668; prefer pipx.)

### From source / for development

```bash
git clone https://github.com/luoli523/ai-convo-exporter
cd ai-convo-exporter
./install.sh
```

`./install.sh` creates a bash wrapper at `~/.local/bin/ai-convo-exporter`
pointing at this checkout, then runs `setup`. If `ai-convo-exporter` is
already on PATH (e.g., from a prior pipx install), the wrapper step is
skipped so we don't clobber it.

### Setup options

`setup` (and `./install.sh`) accept the same options:

```bash
ai-convo-exporter setup --vault "$HOME/Documents/obsidian"   # skip detection
ai-convo-exporter setup --dry-run                            # preview only
./install.sh --backfill                                      # also import history
```

Without `--vault`, `setup` reads Obsidian's vault registry
(`~/Library/Application Support/obsidian/obsidian.json` on macOS,
`~/.config/obsidian/obsidian.json` on Linux) and prompts:

- One vault → `[Y/n/m]` (m enters a manual path).
- Multiple vaults → numbered list, currently open first, `m` for manual.
- If Obsidian is not installed or has never been opened, `setup` exits
  with instructions and writes nothing.

`setup` is idempotent. Hook entries are merged in place rather than
appended. Re-running without `--vault` marks the previously configured
vault as `[current]` and selects it by default.

What `setup` writes:

- `~/.config/ai-convo-exporter/config.json`
- A Claude Code `Stop` hook in `~/.claude/settings.json`
- A Codex `Stop` hook in `~/.codex/hooks.json`
- `[features] hooks = true` in `~/.codex/config.toml`
- The vault path under Codex `sandbox_workspace_write.writable_roots`
  so the hook can write notes while Codex runs in workspace-write mode.

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
