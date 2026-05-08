#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


DEFAULT_CONVERSATIONS_DIR = "AI Conversations"
DEFAULT_TIMEZONE = "Asia/Singapore"
HOOK_STATUS = {"continue": True, "suppressOutput": True}

SKIP_PREFIXES = (
    "<environment_context>",
    "<system-reminder>",
    "<local-command-caveat>",
    "<local-command-stdout>",
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "# AGENTS.md instructions",
)


@dataclass
class ExportConfig:
    vault_dir: Path
    conversations_dir: str = DEFAULT_CONVERSATIONS_DIR
    timezone: str = DEFAULT_TIMEZONE
    machine: str = field(default_factory=socket.gethostname)
    archive_raw: bool = True


@dataclass
class Message:
    role: str
    text: str
    timestamp: str = ""


@dataclass
class Transcript:
    provider: str
    session_id: str
    messages: list[Message]
    created: datetime
    updated: datetime
    cwd: str = ""
    git_repo: str = ""
    git_branch: str = ""
    title: str = ""


@dataclass
class ExportResult:
    markdown_path: Path
    raw_path: Path
    project: str
    project_slug: str
    session_id: str


def config_path(home: Path | None = None) -> Path:
    override = os.environ.get("AI_CONVO_CONFIG")
    if override:
        return Path(override).expanduser()
    if home is None:
        home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return config_home / "ai-convo-exporter" / "config.json"


def default_vault_dir(home: Path | None = None) -> Path:
    env_vault = os.environ.get("AI_CONVO_VAULT")
    if env_vault:
        return Path(env_vault).expanduser()
    if home is None:
        home = Path.home()
    candidates = [
        home / "Documents" / "Obsidian Vault",
        home / "Obsidian Vault",
        home / "Documents" / "Obsidian",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_config(home: Path | None = None) -> ExportConfig:
    path = config_path(home)
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    vault = Path(os.environ.get("AI_CONVO_VAULT") or data.get("vault_dir") or default_vault_dir(home))
    return ExportConfig(
        vault_dir=vault.expanduser(),
        conversations_dir=data.get("conversations_dir", DEFAULT_CONVERSATIONS_DIR),
        timezone=data.get("timezone", DEFAULT_TIMEZONE),
        machine=data.get("machine", socket.gethostname()),
        archive_raw=bool(data.get("archive_raw", True)),
    )


def save_config(config: ExportConfig, home: Path | None = None) -> Path:
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "vault_dir": str(config.vault_dir),
        "conversations_dir": config.conversations_dir,
        "timezone": config.timezone,
        "machine": config.machine,
        "archive_raw": config.archive_raw,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def slugify(value: str, fallback: str = "unknown") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or fallback


def safe_filename(value: str, max_len: int = 72) -> str:
    value = value.replace("\n", " ").strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return (value[:max_len].strip() or "untitled")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_local(dt: datetime, timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    return dt.astimezone(tz)


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in {"text", "input_text", "output_text"}:
            parts.append(str(block.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def is_noise(text: str) -> bool:
    stripped = text.strip()
    return not stripped or any(stripped.startswith(prefix) for prefix in SKIP_PREFIXES)


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def parse_codex_transcript(path: Path, cwd: str = "") -> Transcript:
    messages: list[Message] = []
    timestamps: list[datetime] = []
    session_id = path.stem
    transcript_cwd = cwd
    git_repo = ""
    git_branch = ""
    title = ""

    for entry in read_jsonl(path):
        timestamp = entry.get("timestamp")
        parsed_time = parse_time(timestamp)
        if parsed_time:
            timestamps.append(parsed_time)

        if entry.get("type") == "session_meta":
            payload = entry.get("payload", {})
            if isinstance(payload, dict):
                session_id = str(payload.get("id") or session_id)
                transcript_cwd = str(payload.get("cwd") or transcript_cwd)
                meta_time = parse_time(payload.get("timestamp"))
                if meta_time:
                    timestamps.append(meta_time)
                git = payload.get("git", {})
                if isinstance(git, dict):
                    git_repo = str(git.get("repository_url") or git_repo)
                    git_branch = str(git.get("branch") or git_branch)
            continue

        payload = entry.get("payload", {})
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = extract_text(payload.get("content"))
        if is_noise(text):
            continue
        if role == "user" and not title:
            title = text
        messages.append(Message(role=role, text=text, timestamp=str(timestamp or "")))

    now = datetime.now(timezone.utc)
    created = min(timestamps) if timestamps else now
    updated = max(timestamps) if timestamps else created
    return Transcript(
        provider="codex",
        session_id=session_id,
        messages=messages,
        created=created,
        updated=updated,
        cwd=transcript_cwd,
        git_repo=git_repo,
        git_branch=git_branch,
        title=title,
    )


def parse_claude_transcript(path: Path, cwd: str = "") -> Transcript:
    messages: list[Message] = []
    timestamps: list[datetime] = []
    session_id = path.stem
    transcript_cwd = cwd
    git_branch = ""
    title = ""

    for entry in read_jsonl(path):
        timestamp = entry.get("timestamp")
        parsed_time = parse_time(timestamp)
        if parsed_time:
            timestamps.append(parsed_time)

        if entry.get("cwd"):
            transcript_cwd = str(entry.get("cwd"))
        if entry.get("sessionId"):
            session_id = str(entry.get("sessionId"))
        if entry.get("gitBranch"):
            git_branch = str(entry.get("gitBranch"))

        if entry.get("isMeta"):
            continue
        entry_type = entry.get("type")
        if entry_type not in {"user", "assistant"}:
            continue
        message = entry.get("message", {})
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in {"user", "assistant"}:
            role = entry_type
        text = extract_text(message.get("content"))
        if is_noise(text):
            continue
        if role == "user" and not title:
            title = text
        messages.append(Message(role=role, text=text, timestamp=str(timestamp or "")))

    now = datetime.now(timezone.utc)
    created = min(timestamps) if timestamps else now
    updated = max(timestamps) if timestamps else created
    return Transcript(
        provider="claude",
        session_id=session_id,
        messages=messages,
        created=created,
        updated=updated,
        cwd=transcript_cwd,
        git_branch=git_branch,
        title=title,
    )


def parse_transcript(provider: str, path: Path, cwd: str = "") -> Transcript:
    provider = provider.lower()
    if provider == "codex":
        return parse_codex_transcript(path, cwd)
    if provider == "claude":
        return parse_claude_transcript(path, cwd)
    raise ValueError(f"Unsupported provider: {provider}")


def find_git_dir(cwd: str) -> Path | None:
    if not cwd:
        return None
    current = Path(cwd).expanduser()
    if not current.exists():
        return None
    if current.is_file():
        current = current.parent
    for directory in [current, *current.parents]:
        dotgit = directory / ".git"
        if dotgit.is_dir():
            return dotgit
        if dotgit.is_file():
            text = dotgit.read_text(encoding="utf-8", errors="ignore").strip()
            if text.startswith("gitdir:"):
                git_path = Path(text.split(":", 1)[1].strip())
                if not git_path.is_absolute():
                    git_path = directory / git_path
                return git_path
    return None


def read_git_context(cwd: str) -> tuple[str, str]:
    git_dir = find_git_dir(cwd)
    if git_dir is None:
        return "", ""

    remote = ""
    config_path = git_dir / "config"
    if config_path.exists():
        parser = configparser.ConfigParser()
        try:
            parser.read(config_path, encoding="utf-8")
            if parser.has_section('remote "origin"'):
                remote = parser.get('remote "origin"', "url", fallback="")
        except configparser.Error:
            remote = ""

    branch = ""
    head_path = git_dir / "HEAD"
    if head_path.exists():
        head = head_path.read_text(encoding="utf-8", errors="ignore").strip()
        if head.startswith("ref: refs/heads/"):
            branch = head.removeprefix("ref: refs/heads/")
        elif head:
            branch = head[:12]
    return remote, branch


def repo_id_from_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""

    path = ""
    if "://" in url:
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")
    elif ":" in url and not url.startswith("/"):
        path = url.split(":", 1)[1]
    else:
        return ""

    path = re.sub(r"\.git$", "", path)
    path = path.strip("/")
    return path


def project_identity(transcript: Transcript) -> tuple[str, str, str, str]:
    git_repo = transcript.git_repo
    git_branch = transcript.git_branch
    detected_repo, detected_branch = read_git_context(transcript.cwd)
    git_repo = git_repo or detected_repo
    git_branch = git_branch or detected_branch

    repo_id = repo_id_from_url(git_repo)
    if repo_id:
        project = repo_id
        project_slug = "__".join(slugify(segment) for segment in repo_id.split("/"))
    else:
        name = Path(transcript.cwd).name if transcript.cwd else "unknown"
        project = name
        project_slug = slugify(name)
    return project, project_slug, git_repo, git_branch


def yaml_value(value: str) -> str:
    if value == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./@:+ -]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def render_markdown(
    transcript: Transcript,
    config: ExportConfig,
    project: str,
    project_slug: str,
    git_repo: str,
    git_branch: str,
    raw_rel_path: str,
) -> str:
    created = to_local(transcript.created, config.timezone).isoformat()
    updated = to_local(transcript.updated, config.timezone).isoformat()
    first_title = transcript.title or next((m.text for m in transcript.messages if m.role == "user"), "")
    title = safe_filename(first_title or transcript.session_id, 88)

    lines = [
        "---",
        "type: ai-conversation",
        f"provider: {transcript.provider}",
        f"session_id: {transcript.session_id}",
        f"project: {yaml_value(project)}",
        f"project_slug: {project_slug}",
        f"created: {created}",
        f"updated: {updated}",
        f"cwd: {yaml_value(transcript.cwd)}",
        f"git_repo: {yaml_value(git_repo)}",
        f"git_branch: {yaml_value(git_branch)}",
        f"machine: {yaml_value(config.machine)}",
        f"raw_transcript: {yaml_value(raw_rel_path)}",
        "tags:",
        "  - ai/conversation",
        f"  - provider/{transcript.provider}",
        f"  - project/{project_slug}",
        "---",
        "",
        f"# {title}",
        "",
        f"- Provider: `{transcript.provider}`",
        f"- Project: `{project}`",
        f"- Session: `{transcript.session_id}`",
        "",
        "---",
        "",
    ]

    for message in transcript.messages:
        label = "User" if message.role == "user" else "Assistant"
        lines.extend([f"## {label}", ""])
        if message.timestamp:
            lines.extend([f"> {message.timestamp}", ""])
        lines.extend([message.text, "", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_project_index(project_dir: Path, project: str, project_slug: str, conversations_dir: str) -> None:
    index_path = project_dir / "_index.md"
    dataview_path = f"{conversations_dir}/Projects/{project_slug}/sessions"
    index = (
        f"# {project}\n\n"
        f"- Project slug: `{project_slug}`\n"
        "- Scope: Codex and Claude Code conversations for this project.\n\n"
        "```dataview\n"
        f'TABLE provider, created, file.link AS session FROM "{dataview_path}"\n'
        "SORT created DESC\n"
        "```\n"
    )
    index_path.write_text(index, encoding="utf-8")


def export_transcript(provider: str, transcript_path: Path, config: ExportConfig, cwd: str = "") -> ExportResult:
    transcript_path = transcript_path.expanduser()
    if not transcript_path.exists():
        raise FileNotFoundError(transcript_path)

    transcript = parse_transcript(provider, transcript_path, cwd)
    if not transcript.messages:
        raise ValueError(f"No exportable messages in {transcript_path}")

    project, project_slug, git_repo, git_branch = project_identity(transcript)
    project_dir = config.vault_dir / config.conversations_dir / "Projects" / project_slug
    sessions_dir = project_dir / "sessions"
    raw_dir = project_dir / "raw" / transcript.provider
    sessions_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"{transcript.session_id}.jsonl"
    if config.archive_raw:
        shutil.copy2(transcript_path, raw_path)

    local_created = to_local(transcript.created, config.timezone)
    title = safe_filename(transcript.title or transcript.session_id)
    filename = (
        f"{local_created.strftime('%Y-%m-%d %H%M')} "
        f"{transcript.provider} {transcript.session_id[:8]} {title}.md"
    )
    markdown_path = sessions_dir / filename
    raw_rel_path = os.path.relpath(raw_path, markdown_path.parent)
    markdown = render_markdown(
        transcript=transcript,
        config=config,
        project=project,
        project_slug=project_slug,
        git_repo=git_repo,
        git_branch=git_branch,
        raw_rel_path=raw_rel_path,
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    write_project_index(project_dir, project, project_slug, config.conversations_dir)
    return ExportResult(
        markdown_path=markdown_path,
        raw_path=raw_path,
        project=project,
        project_slug=project_slug,
        session_id=transcript.session_id,
    )


def infer_provider(path: Path) -> str:
    text = str(path)
    if ".claude" in text:
        return "claude"
    if ".codex" in text:
        return "codex"
    raise ValueError("Provider is required when transcript path is ambiguous")


def iter_default_transcripts(provider: str, home: Path) -> Iterable[Path]:
    provider = provider.lower()
    if provider in {"claude", "all"}:
        yield from (home / ".claude" / "projects").glob("**/*.jsonl")
    if provider in {"codex", "all"}:
        yield from (home / ".codex" / "sessions").glob("**/*.jsonl")
        yield from (home / ".codex" / "archived_sessions").glob("*.jsonl")


def merge_claude_settings(settings: dict[str, Any], command: str) -> dict[str, Any]:
    result = dict(settings)
    hooks = dict(result.get("hooks") or {})
    stop_groups = list(hooks.get("Stop") or [])
    hook_entry = {
        "type": "command",
        "command": command,
        "timeout": 30,
        "statusMessage": "Saving conversation to Obsidian...",
    }

    for group in stop_groups:
        entries = group.setdefault("hooks", [])
        entries[:] = [
            entry
            for entry in entries
            if entry.get("command") != command
            and "export-to-obsidian.py" not in str(entry.get("command", ""))
        ]

    stop_groups = [
        group for group in stop_groups if group.get("hooks") or group.get("matcher")
    ]
    stop_groups.append({"hooks": [hook_entry]})
    hooks["Stop"] = stop_groups
    result["hooks"] = hooks
    return result


def merge_codex_hooks(hooks_config: dict[str, Any], command: str) -> dict[str, Any]:
    result = dict(hooks_config)
    hooks = dict(result.get("hooks") or {})
    stop_groups = list(hooks.get("Stop") or [])
    hook_entry = {
        "type": "command",
        "command": command,
        "timeout": 30,
        "statusMessage": "Saving conversation to Obsidian...",
    }

    for group in stop_groups:
        entries = group.setdefault("hooks", [])
        entries[:] = [entry for entry in entries if entry.get("command") != command]

    stop_groups = [
        group for group in stop_groups if group.get("hooks") or group.get("matcher")
    ]
    stop_groups.append({"hooks": [hook_entry]})
    hooks["Stop"] = stop_groups
    result["hooks"] = hooks
    return result


def merge_codex_config_toml(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    in_features = False
    saw_features = False
    saw_codex_hooks = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_features and not saw_codex_hooks:
                output.append("codex_hooks = true")
                saw_codex_hooks = True
            in_features = stripped == "[features]"
            saw_features = saw_features or in_features
        if in_features and re.match(r"codex_hooks\s*=", stripped):
            output.append("codex_hooks = true")
            saw_codex_hooks = True
            continue
        output.append(line)

    if in_features and not saw_codex_hooks:
        output.append("codex_hooks = true")
    if not saw_features:
        if output and output[-1].strip():
            output.append("")
        output.extend(["[features]", "codex_hooks = true"])
    return "\n".join(output).rstrip() + "\n"


def read_json_file(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    return data if isinstance(data, dict) else default


def install_config(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser() if args.home else Path.home()
    vault_dir = Path(args.vault).expanduser() if args.vault else default_vault_dir(home)
    command = args.command or "$HOME/.local/bin/ai-convo-exporter hook"
    config = ExportConfig(
        vault_dir=vault_dir,
        conversations_dir=args.conversations_dir,
        timezone=args.timezone,
        machine=args.machine or socket.gethostname(),
    )

    if args.dry_run:
        print(f"Would write config: {config_path(home)}")
        print(f"Would set vault: {config.vault_dir}")
        print(f"Would install Claude hook command: {command} --provider claude")
        print(f"Would install Codex hook command: {command} --provider codex")
        return 0

    save_config(config, home)

    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_settings_path = claude_dir / "settings.json"
    claude_settings = read_json_file(claude_settings_path, {})
    claude_settings = merge_claude_settings(claude_settings, f"{command} --provider claude")
    claude_settings_path.write_text(
        json.dumps(claude_settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_hooks_path = codex_dir / "hooks.json"
    codex_hooks = read_json_file(codex_hooks_path, {"hooks": {}})
    codex_hooks = merge_codex_hooks(codex_hooks, f"{command} --provider codex")
    codex_hooks_path.write_text(
        json.dumps(codex_hooks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    codex_config_path = codex_dir / "config.toml"
    codex_config = codex_config_path.read_text(encoding="utf-8") if codex_config_path.exists() else ""
    codex_config_path.write_text(merge_codex_config_toml(codex_config), encoding="utf-8")

    print(f"Installed ai-convo-exporter config at {config_path(home)}")
    print(f"Vault: {config.vault_dir}")
    return 0


def command_hook(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
        transcript_value = payload.get("transcript_path")
        if not transcript_value:
            print(json.dumps(HOOK_STATUS))
            return 0
        transcript_path = Path(transcript_value).expanduser()
        provider = args.provider or infer_provider(transcript_path)
        config = load_config()
        export_transcript(provider, transcript_path, config, cwd=str(payload.get("cwd") or ""))
    except Exception as exc:
        status = {
            **HOOK_STATUS,
            "systemMessage": f"ai-convo-exporter failed: {exc}",
        }
        print(json.dumps(status, ensure_ascii=False))
        return 0

    print(json.dumps(HOOK_STATUS))
    return 0


def command_export(args: argparse.Namespace) -> int:
    config = load_config()
    provider = args.provider or infer_provider(Path(args.transcript))
    result = export_transcript(provider, Path(args.transcript), config, cwd=args.cwd or "")
    print(result.markdown_path)
    return 0


def command_scan(args: argparse.Namespace) -> int:
    config = load_config()
    home = Path(args.home).expanduser() if args.home else Path.home()
    exported = 0
    skipped = 0
    for path in iter_default_transcripts(args.provider, home):
        try:
            provider = infer_provider(path)
            export_transcript(provider, path, config)
            exported += 1
        except Exception:
            skipped += 1
    print(f"Exported {exported} transcripts, skipped {skipped}.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser() if args.home else Path.home()
    config = load_config(home)
    print(f"Config: {config_path(home)}")
    print(f"Vault: {config.vault_dir}")
    print(f"Conversations dir: {config.conversations_dir}")
    print(f"Timezone: {config.timezone}")
    print(f"Claude settings: {home / '.claude' / 'settings.json'}")
    print(f"Codex hooks: {home / '.codex' / 'hooks.json'}")
    print(f"Codex config: {home / '.codex' / 'config.toml'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-convo-exporter")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    hook = subparsers.add_parser("hook", help="Run from a Codex or Claude Code hook")
    hook.add_argument("--provider", choices=["codex", "claude"])
    hook.set_defaults(func=command_hook)

    export = subparsers.add_parser("export", help="Export one transcript")
    export.add_argument("transcript")
    export.add_argument("--provider", choices=["codex", "claude"])
    export.add_argument("--cwd")
    export.set_defaults(func=command_export)

    scan = subparsers.add_parser("scan", help="Export discovered local transcripts")
    scan.add_argument("--provider", choices=["codex", "claude", "all"], default="all")
    scan.add_argument("--home")
    scan.set_defaults(func=command_scan)

    backfill = subparsers.add_parser("backfill", help="Alias for scan")
    backfill.add_argument("--provider", choices=["codex", "claude", "all"], default="all")
    backfill.add_argument("--home")
    backfill.set_defaults(func=command_scan)

    install = subparsers.add_parser("install-config", help="Write local config and hooks")
    install.add_argument("--vault")
    install.add_argument("--home")
    install.add_argument("--command")
    install.add_argument("--conversations-dir", default=DEFAULT_CONVERSATIONS_DIR)
    install.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    install.add_argument("--machine")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=install_config)

    doctor = subparsers.add_parser("doctor", help="Show active config and expected files")
    doctor.add_argument("--home")
    doctor.set_defaults(func=command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
