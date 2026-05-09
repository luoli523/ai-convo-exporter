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
    kind: str = "discussion"  # "discussion" or "action"


@dataclass
class ToolUsage:
    files: list[str] = field(default_factory=list)
    tools: dict[str, int] = field(default_factory=dict)

    @property
    def total_calls(self) -> int:
        return sum(self.tools.values())


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
    tool_usage: ToolUsage = field(default_factory=ToolUsage)


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


def title_slug(value: str, fallback: str, max_len: int = 50) -> str:
    """Filename-safe slug that preserves CJK / unicode word characters.

    Lowercases ASCII letters; replaces any non-letter/digit (and underscores)
    with `-`; strips filesystem-illegal characters; truncates by character
    count. Falls back when the result is empty.
    """
    value = value.replace("\n", " ").strip().lower()
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", value)
    value = re.sub(r"[^\w]|_", "-", value, flags=re.UNICODE)
    value = re.sub(r"-+", "-", value).strip("-")
    if len(value) > max_len:
        value = value[:max_len].rstrip("-")
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


def content_has_tool_use(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in content
    )


DECISION_PATTERNS = [
    r"我建议",
    r"我倾向",
    r"我推荐",
    r"我觉得应该",
    r"我决定",
    r"决策[:：]",
    r"结论[:：]",
    r"\bI recommend\b",
    r"\bI'd recommend\b",
    r"\bI suggest\b",
    r"\blet's go with\b",
    r"\blet's use\b",
    r"\blet's pick\b",
    r"\bdecision[:：]",
    r"\bgoing with\b",
    r"\bdecided to\b",
]
_DECISION_RE = re.compile("|".join(DECISION_PATTERNS), flags=re.IGNORECASE)


def find_decision_snippet(text: str, window: int = 80) -> str | None:
    """Return a short snippet around the first decision keyword, or None."""
    match = _DECISION_RE.search(text)
    if not match:
        return None
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    snippet = text[start:end].replace("\n", " ").strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


def _parse_frontmatter_value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Minimal YAML frontmatter reader for our own writer's output shape."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out: dict[str, Any] = {}
    current_list: list[str] | None = None
    for line in block.split("\n"):
        if not line.strip():
            current_list = None
            continue
        if line.startswith("  - ") and current_list is not None:
            current_list.append(_parse_frontmatter_value(line[4:]))
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not value:
                current_list = []
                out[key] = current_list
            else:
                out[key] = _parse_frontmatter_value(value)
                current_list = None
    return out


def compute_session_stats(transcript: Transcript) -> dict[str, int]:
    discussion = sum(
        1 for m in transcript.messages if m.role == "assistant" and m.kind == "discussion"
    )
    action = sum(
        1 for m in transcript.messages if m.role == "assistant" and m.kind == "action"
    )
    decisions = sum(
        1 for m in transcript.messages
        if m.role == "assistant" and find_decision_snippet(m.text) is not None
    )
    return {"discussion": discussion, "action": action, "decisions": decisions}


def render_daily_entry(
    note_stem: str,
    session_id: str,
    topic: str,
    stats: dict[str, int],
) -> str:
    topic = (topic or "").replace("\n", " ").strip()
    if len(topic) > 100:
        topic = topic[:100].rstrip() + "..."
    counts = f"{stats['discussion']} discussion · {stats['action']} action"
    if stats.get("decisions"):
        counts += f" · {stats['decisions']} decisions"
    body = topic if topic else "(no topic)"
    return f"- [[{note_stem}]] — {body} ({counts}) <!-- session_id: {session_id} -->"


def update_daily_note(daily_path: Path, entry: str, session_id: str, date_str: str) -> None:
    marker = f"<!-- session_id: {session_id} -->"
    daily_path.parent.mkdir(parents=True, exist_ok=True)
    if daily_path.exists():
        text = daily_path.read_text(encoding="utf-8")
    else:
        text = f"# {date_str}\n\n## AI sessions\n"

    lines = text.splitlines()

    for i, line in enumerate(lines):
        if marker in line:
            lines[i] = entry
            daily_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

    if "## AI sessions" not in text:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["## AI sessions", entry])
    else:
        section_start = next(
            i for i, l in enumerate(lines) if l.strip() == "## AI sessions"
        )
        end = len(lines)
        for j in range(section_start + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break
        while end > section_start + 1 and lines[end - 1].strip() == "":
            end -= 1
        lines.insert(end, entry)

    daily_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def find_related_sessions(
    sessions_dir: Path,
    current_session_id: str,
    current_files: list[str],
    max_results: int = 5,
) -> list[tuple[str, int]]:
    """Return [(note_stem, overlap_count)] for sessions sharing files."""
    file_set = set(current_files)
    if not file_set or not sessions_dir.exists():
        return []
    candidates: list[tuple[str, int]] = []
    for path in sessions_dir.glob("*.md"):
        fm = read_frontmatter(path)
        if not fm:
            continue
        if fm.get("session_id") == current_session_id:
            continue
        other = fm.get("related_files") or []
        if not isinstance(other, list):
            continue
        overlap = len(file_set & set(str(x) for x in other))
        if overlap > 0:
            candidates.append((path.stem, overlap))
    candidates.sort(key=lambda c: (-c[1], c[0]))
    return candidates[:max_results]


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


_FILE_PATH_KEYS = ("file_path", "path", "filename", "file", "notebook_path")


def _record_file(usage: ToolUsage, value: Any) -> None:
    if isinstance(value, str) and value and value not in usage.files:
        usage.files.append(value)


def extract_claude_tool_usage(path: Path) -> ToolUsage:
    usage = ToolUsage()
    for entry in read_jsonl(path):
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if isinstance(name, str) and name:
                usage.tools[name] = usage.tools.get(name, 0) + 1
            inp = block.get("input")
            if isinstance(inp, dict):
                for key in _FILE_PATH_KEYS:
                    _record_file(usage, inp.get(key))
    return usage


def extract_codex_tool_usage(path: Path) -> ToolUsage:
    usage = ToolUsage()
    for entry in read_jsonl(path):
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "function_call":
            continue
        name = payload.get("name")
        if isinstance(name, str) and name:
            usage.tools[name] = usage.tools.get(name, 0) + 1
        args_raw = payload.get("arguments")
        args: Any = None
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = None
        elif isinstance(args_raw, dict):
            args = args_raw
        if isinstance(args, dict):
            for key in _FILE_PATH_KEYS:
                _record_file(usage, args.get(key))
    return usage


def extract_tool_usage(provider: str, path: Path) -> ToolUsage:
    p = provider.lower()
    if p == "claude":
        return extract_claude_tool_usage(path)
    if p == "codex":
        return extract_codex_tool_usage(path)
    return ToolUsage()


def relativize_to_cwd(paths: list[str], cwd: str) -> list[str]:
    if not cwd:
        return list(paths)
    cwd_path = Path(cwd)
    out: list[str] = []
    for raw in paths:
        try:
            candidate = Path(raw)
        except (TypeError, ValueError):
            out.append(raw)
            continue
        if candidate.is_absolute():
            try:
                out.append(str(candidate.relative_to(cwd_path)))
                continue
            except ValueError:
                pass
        out.append(raw)
    return out


def parse_codex_transcript(path: Path, cwd: str = "") -> Transcript:
    messages: list[Message] = []
    timestamps: list[datetime] = []
    session_id = path.stem
    transcript_cwd = cwd
    git_repo = ""
    git_branch = ""
    title = ""
    last_assistant_idx = -1

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
        if not isinstance(payload, dict):
            continue
        payload_type = payload.get("type")
        if payload_type == "function_call":
            if last_assistant_idx >= 0:
                messages[last_assistant_idx].kind = "action"
            continue
        if payload_type != "message":
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
        if role == "assistant":
            last_assistant_idx = len(messages) - 1
        else:
            last_assistant_idx = -1

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
    last_assistant_idx = -1

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
        content = message.get("content")
        has_tools = content_has_tool_use(content)
        text = extract_text(content)

        # Pure tool_use entry (Claude Code splits text and tool_use across entries):
        # the previous text-bearing assistant message is the one doing the action.
        if entry_type == "assistant" and has_tools and not text:
            if last_assistant_idx >= 0:
                messages[last_assistant_idx].kind = "action"
            continue

        if is_noise(text):
            continue

        role = message.get("role")
        if role not in {"user", "assistant"}:
            role = entry_type
        if role == "user" and not title:
            title = text
        kind = "action" if (role == "assistant" and has_tools) else "discussion"
        messages.append(Message(role=role, text=text, timestamp=str(timestamp or ""), kind=kind))
        if role == "assistant":
            last_assistant_idx = len(messages) - 1
        else:
            last_assistant_idx = -1

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
        transcript = parse_codex_transcript(path, cwd)
    elif provider == "claude":
        transcript = parse_claude_transcript(path, cwd)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    transcript.tool_usage = extract_tool_usage(provider, path)
    return transcript


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
    related_sessions: list[tuple[str, int]] | None = None,
) -> str:
    created = to_local(transcript.created, config.timezone).isoformat()
    updated = to_local(transcript.updated, config.timezone).isoformat()
    first_title = transcript.title or next((m.text for m in transcript.messages if m.role == "user"), "")
    title = safe_filename(first_title or transcript.session_id, 88)

    related_files = relativize_to_cwd(transcript.tool_usage.files, transcript.cwd)[:20]
    tools_used = sorted(transcript.tool_usage.tools.keys())

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
        f"tool_call_count: {transcript.tool_usage.total_calls}",
    ]
    if tools_used:
        lines.append("tools_used:")
        for name in tools_used:
            lines.append(f"  - {name}")
    if related_files:
        lines.append("related_files:")
        for path in related_files:
            lines.append(f"  - {yaml_value(path)}")
    if related_sessions:
        lines.append("related_sessions:")
        for stem, _ in related_sessions:
            lines.append(f'  - "[[{stem}]]"')
    discussion_count = sum(
        1 for m in transcript.messages if m.role == "assistant" and m.kind == "discussion"
    )
    action_count = sum(
        1 for m in transcript.messages if m.role == "assistant" and m.kind == "action"
    )
    decision_count = sum(
        1 for m in transcript.messages
        if m.role == "assistant" and find_decision_snippet(m.text) is not None
    )
    if decision_count:
        lines.append(f"decision_count: {decision_count}")
    lines.extend([
        "tags:",
        "  - ai/conversation",
        f"  - provider/{transcript.provider}",
        f"  - project/{project_slug}",
        "---",
        "",
        f"# {title}",
        "",
    ])
    lines.extend(render_tldr(
        first_user=transcript.title or first_title,
        discussion=discussion_count,
        action=action_count,
        files=len(related_files),
        tool_calls=transcript.tool_usage.total_calls,
        decisions=decision_count,
    ))
    lines.extend([
        f"- Provider: `{transcript.provider}`",
        f"- Project: `{project}`",
        f"- Session: `{transcript.session_id}`",
        "",
        "---",
        "",
    ])

    for message in transcript.messages:
        lines.extend(render_message(message))
    if related_sessions:
        lines.extend(["## Related sessions", ""])
        for stem, overlap in related_sessions:
            label = "shared file" if overlap == 1 else "shared files"
            lines.append(f"- [[{stem}]] ({overlap} {label})")
        lines.extend(["", "---", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_tldr(
    first_user: str,
    discussion: int,
    action: int,
    files: int,
    tool_calls: int,
    decisions: int,
) -> list[str]:
    topic = (first_user or "").replace("\n", " ").strip()
    if len(topic) > 120:
        topic = topic[:120].rstrip() + "..."
    lines = ["> [!tldr]+ TL;DR"]
    if topic:
        lines.append(f"> - **Topic**: {topic}")
    lines.append(f"> - **Turns**: {discussion} discussion · {action} action")
    if files:
        lines.append(f"> - **Files touched**: {files}")
    if tool_calls:
        lines.append(f"> - **Tool calls**: {tool_calls}")
    if decisions:
        lines.append(f"> - **Decisions flagged**: {decisions} (see `[!decision]` callouts below)")
    lines.extend(["", "---", ""])
    return lines


def render_message(message: Message) -> list[str]:
    label = "User" if message.role == "user" else "Assistant"
    decision_snippet = (
        find_decision_snippet(message.text) if message.role == "assistant" else None
    )

    if message.kind == "action" and message.role == "assistant":
        lines = [f"## {label}", ""]
        if message.timestamp:
            lines.extend([f"> {message.timestamp}", ""])
        if decision_snippet:
            lines.extend(_decision_callout_lines(decision_snippet))
        lines.append("> [!action]- action")
        for content_line in message.text.split("\n"):
            lines.append(f"> {content_line}" if content_line else ">")
        lines.extend(["", "---", ""])
        return lines

    lines = [f"## {label}", ""]
    if message.timestamp:
        lines.extend([f"> {message.timestamp}", ""])
    if decision_snippet:
        lines.extend(_decision_callout_lines(decision_snippet))
    lines.extend([message.text, "", "---", ""])
    return lines


def _decision_callout_lines(snippet: str) -> list[str]:
    safe = snippet.replace("\n", " ")
    return [
        "> [!decision]+ Decision",
        f"> {safe}",
        "",
    ]


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


def remove_stale_session_notes(sessions_dir: Path, current_path: Path, session_id: str) -> None:
    marker = f"session_id: {session_id}"
    for path in sessions_dir.glob("*.md"):
        if path == current_path:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if marker in text:
            path.unlink()


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

    local_updated = to_local(transcript.updated, config.timezone)
    title = title_slug(
        transcript.title or transcript.session_id,
        transcript.session_id[:8] or "session",
    )
    filename = f"{local_updated.strftime('%Y%m%d')}-{transcript.provider}-{title}.md"
    markdown_path = sessions_dir / filename
    raw_rel_path = os.path.relpath(raw_path, markdown_path.parent)
    related_files = relativize_to_cwd(transcript.tool_usage.files, transcript.cwd)
    related_sessions = find_related_sessions(
        sessions_dir, transcript.session_id, related_files
    )
    markdown = render_markdown(
        transcript=transcript,
        config=config,
        project=project,
        project_slug=project_slug,
        git_repo=git_repo,
        git_branch=git_branch,
        raw_rel_path=raw_rel_path,
        related_sessions=related_sessions,
    )
    markdown_path.write_text(markdown, encoding="utf-8")
    remove_stale_session_notes(sessions_dir, markdown_path, transcript.session_id)
    write_project_index(project_dir, project, project_slug, config.conversations_dir)

    daily_dir = config.vault_dir / config.conversations_dir / "Daily"
    daily_path = daily_dir / f"{local_updated.strftime('%Y-%m-%d')}.md"
    stats = compute_session_stats(transcript)
    topic = transcript.title or next(
        (m.text for m in transcript.messages if m.role == "user"), ""
    )
    entry = render_daily_entry(markdown_path.stem, transcript.session_id, topic, stats)
    update_daily_note(
        daily_path, entry, transcript.session_id, local_updated.strftime("%Y-%m-%d")
    )

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
