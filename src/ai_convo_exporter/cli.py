#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
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
DEFAULT_SAVE_POLICY = "always"
DEFAULT_SAVE_TRIGGERS: list[str] = []
DEFAULT_SKIP_TRIGGERS = ["#nosave"]
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
    save_policy: str = DEFAULT_SAVE_POLICY
    save_triggers: list[str] = field(default_factory=lambda: list(DEFAULT_SAVE_TRIGGERS))
    skip_triggers: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_TRIGGERS))


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
    replace_same_session: bool = True
    append_same_session: bool = False


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
    return home / "Documents" / "obsidian"


def config_string_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
        return [item for item in items if item]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(default)


def normalize_save_policy(value: Any) -> str:
    policy = str(value or DEFAULT_SAVE_POLICY).strip().lower()
    if policy == "manual":
        return "always"
    return policy or DEFAULT_SAVE_POLICY


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
        save_policy=normalize_save_policy(data.get("save_policy", DEFAULT_SAVE_POLICY)),
        save_triggers=config_string_list(data.get("save_triggers"), DEFAULT_SAVE_TRIGGERS),
        skip_triggers=config_string_list(data.get("skip_triggers"), DEFAULT_SKIP_TRIGGERS),
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
        "save_policy": config.save_policy,
        "save_triggers": config.save_triggers,
        "skip_triggers": config.skip_triggers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def safe_filename(value: str, max_len: int = 72, fallback: str = "untitled") -> str:
    value = value.replace("\n", " ").strip()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return (value[:max_len].strip() or fallback)


def ascii_slug(value: str, fallback: str, max_len: int = 72) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    value = value[:max_len].strip("-")
    return value or fallback


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


def trigger_in_text(text: str, triggers: list[str]) -> bool:
    lines = [line.strip().lower() for line in text.splitlines()]
    for trigger in triggers:
        normalized = trigger.strip().lower()
        if not normalized:
            continue
        if normalized in lines:
            return True
    return False


def user_has_trigger(transcript: Transcript, triggers: list[str]) -> bool:
    return any(
        message.role == "user" and trigger_in_text(message.text, triggers)
        for message in transcript.messages
    )


def should_export_from_hook(transcript: Transcript, config: ExportConfig) -> bool:
    return transcript_for_hook_export(transcript, config) is not None


def transcript_for_hook_export(transcript: Transcript, config: ExportConfig) -> Transcript | None:
    if user_has_trigger(transcript, config.skip_triggers):
        return None
    if config.save_policy in {"always", "manual"}:
        return transcript
    return None


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


def repo_name_from_url(url: str) -> str:
    repo_id = repo_id_from_url(url)
    if not repo_id:
        return ""
    return repo_id.rsplit("/", 1)[-1]


def project_identity(transcript: Transcript) -> tuple[str, str, str, str]:
    git_repo = transcript.git_repo
    git_branch = transcript.git_branch
    detected_repo, detected_branch = read_git_context(transcript.cwd)
    git_repo = git_repo or detected_repo
    git_branch = git_branch or detected_branch

    repo_name = repo_name_from_url(git_repo)
    name = repo_name or (Path(transcript.cwd).name if transcript.cwd else "unknown")
    project = safe_filename(name, 80, "unknown")
    project_slug = project
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

    lines.extend(render_message_sections_list(transcript.messages))
    return "\n".join(lines).rstrip() + "\n"


def question_heading(question: Message, fallback: str = "Question") -> str:
    first_line = next((line.strip() for line in question.text.splitlines() if line.strip()), "")
    return safe_filename(first_line, 88, fallback)


def render_question_answer_section(question: Message, answer: Message) -> list[str]:
    heading = question_heading(question)
    question_text = question.text.strip()
    lines = [f"## {heading}", ""]
    if question.timestamp:
        lines.extend([f"> User: {question.timestamp}", ""])
    if question_text and question_text != heading:
        lines.extend([question_text, ""])
    lines.extend(["### Answer", ""])
    if answer.timestamp:
        lines.extend([f"> Assistant: {answer.timestamp}", ""])
    lines.extend([answer.text, "", "---", ""])
    return lines


def render_unpaired_user_section(message: Message) -> list[str]:
    heading = question_heading(message)
    message_text = message.text.strip()
    lines = [f"## {heading}", ""]
    if message.timestamp:
        lines.extend([f"> User: {message.timestamp}", ""])
    if message_text and message_text != heading:
        lines.extend([message_text, ""])
    lines.extend(["---", ""])
    return lines


def render_unpaired_assistant_section(message: Message) -> list[str]:
    lines = ["## Assistant", ""]
    if message.timestamp:
        lines.extend([f"> Assistant: {message.timestamp}", ""])
    lines.extend([message.text, "", "---", ""])
    return lines


def render_message_sections_list(messages: list[Message]) -> list[str]:
    lines: list[str] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        next_message = messages[index + 1] if index + 1 < len(messages) else None
        if message.role == "user" and next_message and next_message.role == "assistant":
            lines.extend(render_question_answer_section(message, next_message))
            index += 2
            continue
        if message.role == "user":
            lines.extend(render_unpaired_user_section(message))
        elif message.role == "assistant":
            lines.extend(render_unpaired_assistant_section(message))
        index += 1
    return lines


def render_message_sections(messages: list[Message]) -> str:
    lines = render_message_sections_list(messages)
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


def session_note_has_id(path: Path, session_id: str) -> bool:
    marker = f"session_id: {session_id}"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return marker in text


def find_session_notes(sessions_dir: Path, session_id: str) -> list[Path]:
    return sorted(
        path for path in sessions_dir.glob("*.md") if session_note_has_id(path, session_id)
    )


def remove_stale_session_notes(sessions_dir: Path, current_path: Path, session_id: str) -> None:
    for path in sessions_dir.glob("*.md"):
        if path == current_path:
            continue
        if session_note_has_id(path, session_id):
            path.unlink()


def update_markdown_updated(markdown: str, updated: datetime, timezone_name: str) -> str:
    updated_text = to_local(updated, timezone_name).isoformat()
    return re.sub(r"^updated: .*$", f"updated: {updated_text}", markdown, count=1, flags=re.MULTILINE)


def append_to_session_note(
    sessions_dir: Path,
    markdown_path: Path,
    transcript: Transcript,
    config: ExportConfig,
) -> Path | None:
    notes = find_session_notes(sessions_dir, transcript.session_id)
    existing_path = markdown_path if markdown_path in notes else (notes[-1] if notes else None)
    if existing_path is None:
        return None
    if existing_path != markdown_path:
        if markdown_path.exists():
            existing_path.unlink()
        else:
            existing_path.rename(markdown_path)
    existing_markdown = markdown_path.read_text(encoding="utf-8")
    existing_markdown = update_markdown_updated(existing_markdown, transcript.updated, config.timezone)
    appended = render_message_sections(transcript.messages)
    if appended.strip() in existing_markdown:
        markdown_path.write_text(existing_markdown, encoding="utf-8")
        remove_stale_session_notes(sessions_dir, markdown_path, transcript.session_id)
        return markdown_path
    markdown_path.write_text(existing_markdown.rstrip() + "\n\n" + appended, encoding="utf-8")
    remove_stale_session_notes(sessions_dir, markdown_path, transcript.session_id)
    return markdown_path


def export_parsed_transcript(
    transcript: Transcript,
    transcript_path: Path,
    config: ExportConfig,
) -> ExportResult:
    transcript_path = transcript_path.expanduser()
    if not transcript_path.exists():
        raise FileNotFoundError(transcript_path)

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

    local_updated = to_local(transcript.updated, config.timezone)
    title = ascii_slug(
        transcript.title or transcript.session_id,
        transcript.session_id[:8] or "session",
    )
    filename = f"{local_updated.strftime('%Y%m%d')}-{transcript.provider}-{title}.md"
    markdown_path = sessions_dir / filename
    raw_rel_path = os.path.relpath(raw_path, markdown_path.parent)
    if transcript.append_same_session:
        appended_path = append_to_session_note(sessions_dir, markdown_path, transcript, config)
        if appended_path is not None:
            write_project_index(project_dir, project, project_slug, config.conversations_dir)
            return ExportResult(
                markdown_path=appended_path,
                raw_path=raw_path,
                project=project,
                project_slug=project_slug,
                session_id=transcript.session_id,
            )

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
    if transcript.replace_same_session:
        remove_stale_session_notes(sessions_dir, markdown_path, transcript.session_id)
    write_project_index(project_dir, project, project_slug, config.conversations_dir)
    return ExportResult(
        markdown_path=markdown_path,
        raw_path=raw_path,
        project=project,
        project_slug=project_slug,
        session_id=transcript.session_id,
    )


def export_transcript(provider: str, transcript_path: Path, config: ExportConfig, cwd: str = "") -> ExportResult:
    transcript_path = transcript_path.expanduser()
    transcript = parse_transcript(provider, transcript_path, cwd)
    return export_parsed_transcript(transcript, transcript_path, config)


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
        "statusMessage": "Exporting conversation to Obsidian...",
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
        "statusMessage": "Exporting conversation to Obsidian...",
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


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_writable_roots_line(writable_roots: list[str]) -> str:
    values = ", ".join(toml_string(root) for root in writable_roots)
    return f"writable_roots = [{values}]"


def merge_writable_roots_line(line: str, writable_root: str) -> str:
    try:
        value = line.split("=", 1)[1].strip()
        roots = ast.literal_eval(value)
    except (IndexError, SyntaxError, ValueError):
        roots = []

    if not isinstance(roots, list):
        roots = []
    normalized = [str(root) for root in roots if isinstance(root, str)]
    if writable_root not in normalized:
        normalized.append(writable_root)
    return render_writable_roots_line(normalized)


def merge_codex_config_toml(text: str, writable_root: str | None = None) -> str:
    lines = text.splitlines()
    output: list[str] = []
    in_features = False
    in_sandbox_workspace_write = False
    saw_features = False
    saw_hooks = False
    saw_sandbox_workspace_write = False
    saw_writable_roots = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_features and not saw_hooks:
                output.append("hooks = true")
                saw_hooks = True
            if in_sandbox_workspace_write and writable_root and not saw_writable_roots:
                output.append(render_writable_roots_line([writable_root]))
                saw_writable_roots = True
            in_features = stripped == "[features]"
            in_sandbox_workspace_write = stripped == "[sandbox_workspace_write]"
            saw_features = saw_features or in_features
            saw_sandbox_workspace_write = saw_sandbox_workspace_write or in_sandbox_workspace_write
        if in_features and re.match(r"(codex_)?hooks\s*=", stripped):
            if not saw_hooks:
                output.append("hooks = true")
                saw_hooks = True
            continue
        if (
            in_sandbox_workspace_write
            and writable_root
            and re.match(r"writable_roots\s*=", stripped)
        ):
            output.append(merge_writable_roots_line(stripped, writable_root))
            saw_writable_roots = True
            continue
        output.append(line)

    if in_features and not saw_hooks:
        output.append("hooks = true")
    if in_sandbox_workspace_write and writable_root and not saw_writable_roots:
        output.append(render_writable_roots_line([writable_root]))
    if not saw_features:
        if output and output[-1].strip():
            output.append("")
        output.extend(["[features]", "hooks = true"])
    if writable_root and not saw_sandbox_workspace_write:
        if output and output[-1].strip():
            output.append("")
        output.extend(
            [
                "[sandbox_workspace_write]",
                render_writable_roots_line([writable_root]),
            ]
        )
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
        print(f"Would add Codex writable root: {config.vault_dir}")
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
    codex_config_path.write_text(
        merge_codex_config_toml(codex_config, str(config.vault_dir)),
        encoding="utf-8",
    )

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
        transcript = parse_transcript(provider, transcript_path, cwd=str(payload.get("cwd") or ""))
        export_transcript_value = transcript_for_hook_export(transcript, config)
        if export_transcript_value is None:
            print(json.dumps(HOOK_STATUS))
            return 0
        export_parsed_transcript(export_transcript_value, transcript_path, config)
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
    print(f"Save policy: {config.save_policy}")
    print(f"Save triggers: {', '.join(config.save_triggers)}")
    print(f"Skip triggers: {', '.join(config.skip_triggers)}")
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
