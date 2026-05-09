#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --vault PATH          Obsidian vault path. Defaults to AI_CONVO_VAULT or ~/Documents/obsidian.
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

if [[ -z "$vault_dir" ]]; then
  vault_dir="$home_dir/Documents/obsidian"
fi

bin_dir="$home_dir/.local/bin"
bin_path="$bin_dir/ai-convo-exporter"
hook_command="\$HOME/.local/bin/ai-convo-exporter hook"
cli_path="$repo_dir/src/ai_convo_exporter/cli.py"

if [[ ! -f "$cli_path" ]]; then
  echo "Cannot find CLI at $cli_path" >&2
  exit 1
fi

if [[ "$dry_run" -eq 1 ]]; then
  echo "Would install command: $bin_path -> $cli_path"
  /usr/bin/env python3 "$cli_path" install-config \
    --home "$home_dir" \
    --vault "$vault_dir" \
    --timezone "$timezone_name" \
    --conversations-dir "$conversations_dir" \
    --command "$hook_command" \
    --dry-run
  exit 0
fi

mkdir -p "$bin_dir"
{
  echo '#!/usr/bin/env bash'
  printf 'exec /usr/bin/env python3 %q "$@"\n' "$cli_path"
} > "$bin_path"
chmod +x "$bin_path"

/usr/bin/env python3 "$cli_path" install-config \
  --home "$home_dir" \
  --vault "$vault_dir" \
  --timezone "$timezone_name" \
  --conversations-dir "$conversations_dir" \
  --command "$hook_command"

if [[ "$backfill" -eq 1 ]]; then
  "$bin_path" backfill --home "$home_dir"
fi

cat <<EOF
Installed ai-convo-exporter.

Command: $bin_path
Vault: $vault_dir

Make sure $bin_dir is in PATH if you want to run ai-convo-exporter directly.
EOF
