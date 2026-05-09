#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --vault PATH          Obsidian vault path. If omitted, the installer reads
                        Obsidian's vault registry and prompts (or reads
                        AI_CONVO_VAULT if set).
  --home PATH           Home directory to configure. Useful for tests.
  --timezone NAME       IANA timezone for note timestamps. Default: Asia/Singapore.
  --conversations-dir NAME
                        Folder under the vault. Default: AI Conversations.
  --backfill            Export existing local Codex and Claude Code transcripts after installing.
  --dry-run             Print what would change without writing files.
  -h, --help            Show this help.
USAGE
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
home_dir="${HOME}"
vault_dir="${AI_CONVO_VAULT:-}"
timezone_name="${AI_CONVO_TIMEZONE:-Asia/Singapore}"
conversations_dir="AI Conversations"
dry_run=0
backfill=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault)
      vault_dir="$2"
      shift 2
      ;;
    --home)
      home_dir="$2"
      shift 2
      ;;
    --timezone)
      timezone_name="$2"
      shift 2
      ;;
    --conversations-dir)
      conversations_dir="$2"
      shift 2
      ;;
    --backfill)
      backfill=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

bin_dir="$home_dir/.local/bin"
bin_path="$bin_dir/ai-convo-exporter"
hook_command="\$HOME/.local/bin/ai-convo-exporter hook"
cli_path="$repo_dir/src/ai_convo_exporter/cli.py"
wrapper_marker="# ai-convo-exporter source-install wrapper"

if [[ ! -f "$cli_path" ]]; then
  echo "Cannot find CLI at $cli_path" >&2
  exit 1
fi

# Detect whether ai-convo-exporter is already on PATH from another install
# (e.g. pipx). If so, don't overwrite that with our bash wrapper. Recognize
# our own wrapper by either the explicit marker or, for legacy installs,
# by the cli.py path pattern.
existing_command="$(command -v ai-convo-exporter 2>/dev/null || true)"
use_external_command=0
if [[ -n "$existing_command" ]]; then
  if grep -qF "$wrapper_marker" "$existing_command" 2>/dev/null; then
    use_external_command=0
  elif grep -qF "ai_convo_exporter/cli.py" "$existing_command" 2>/dev/null; then
    use_external_command=0
  else
    use_external_command=1
  fi
fi

vault_args=()
if [[ -n "$vault_dir" ]]; then
  vault_args=(--vault "$vault_dir")
fi

if [[ "$dry_run" -eq 1 ]]; then
  if [[ "$use_external_command" -eq 1 ]]; then
    echo "Would keep existing command: $existing_command"
  else
    echo "Would install command: $bin_path -> $cli_path"
  fi
  /usr/bin/env python3 "$cli_path" setup \
    --home "$home_dir" \
    "${vault_args[@]}" \
    --timezone "$timezone_name" \
    --conversations-dir "$conversations_dir" \
    --command "$hook_command" \
    --dry-run
  exit 0
fi

if [[ "$use_external_command" -eq 1 ]]; then
  echo "Detected existing ai-convo-exporter at $existing_command"
  echo "Skipping bash wrapper creation; will configure hooks against it."
else
  mkdir -p "$bin_dir"
  {
    echo '#!/usr/bin/env bash'
    echo "$wrapper_marker"
    printf 'exec /usr/bin/env python3 %q "$@"\n' "$cli_path"
  } > "$bin_path"
  chmod +x "$bin_path"
fi

/usr/bin/env python3 "$cli_path" setup \
  --home "$home_dir" \
  "${vault_args[@]}" \
  --timezone "$timezone_name" \
  --conversations-dir "$conversations_dir" \
  --command "$hook_command"

if [[ "$backfill" -eq 1 ]]; then
  if [[ "$use_external_command" -eq 1 ]]; then
    "$existing_command" backfill --home "$home_dir"
  else
    "$bin_path" backfill --home "$home_dir"
  fi
fi

if [[ "$use_external_command" -eq 1 ]]; then
  cat <<EOF

Command: $existing_command (existing)
EOF
else
  cat <<EOF

Command: $bin_path

Make sure $bin_dir is in PATH if you want to run ai-convo-exporter directly.
EOF
fi
