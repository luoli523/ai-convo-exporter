import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_convo_exporter.cli import (
    ExportConfig,
    ascii_slug,
    default_vault_dir,
    export_transcript,
    extract_claude_tool_usage,
    extract_codex_tool_usage,
    merge_claude_settings,
    merge_codex_config_toml,
    merge_codex_hooks,
    relativize_to_cwd,
    title_slug,
)


class ExporterTests(unittest.TestCase):
    def test_exports_codex_transcript_by_stable_git_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "checkout"
            project.mkdir()
            git_dir = project / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text(
                '[remote "origin"]\n'
                "    url = git@github.com:luoli523/ads_attribution.git\n",
                encoding="utf-8",
            )
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

            transcript = root / "codex.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:47:14.000Z",
                                "type": "session_meta",
                                "payload": {
                                    "id": "019e0544-7beb-7983-a458-de94206793f8",
                                    "timestamp": "2026-05-08T01:47:14.000Z",
                                    "cwd": str(project),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:48:00.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": "<environment_context>\n  <cwd>/tmp</cwd>\n</environment_context>",
                                        }
                                    ],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:48:30.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "保存对话"}],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:49:00.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [{"type": "output_text", "text": "已保存"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("codex", transcript, config, cwd=str(project))

            self.assertEqual(result.project, "ads_attribution")
            self.assertEqual(result.project_slug, "ads_attribution")
            self.assertTrue(result.markdown_path.exists())
            self.assertTrue(result.raw_path.exists())
            self.assertEqual(result.markdown_path.name, "20260508-codex-保存对话.md")

            markdown = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("provider: codex", markdown)
            self.assertIn("project: ads_attribution", markdown)
            self.assertIn("project_slug: ads_attribution", markdown)
            self.assertIn("保存对话", markdown)
            self.assertIn("已保存", markdown)

    def test_exports_claude_transcript_and_skips_meta_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "plain-project"
            project.mkdir()
            transcript = root / "claude.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "isMeta": True,
                                "message": {"role": "user", "content": "hidden"},
                                "cwd": str(project),
                                "sessionId": "session-1",
                                "timestamp": "2026-05-08T02:00:00.000Z",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "message": {"role": "user", "content": "开始"},
                                "cwd": str(project),
                                "sessionId": "session-1",
                                "timestamp": "2026-05-08T02:01:00.000Z",
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": [{"type": "text", "text": "继续"}],
                                },
                                "cwd": str(project),
                                "sessionId": "session-1",
                                "timestamp": "2026-05-08T02:02:00.000Z",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("claude", transcript, config, cwd=str(project))

            markdown = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("provider: claude", markdown)
            self.assertIn("project_slug: plain-project", markdown)
            self.assertIn("开始", markdown)
            self.assertIn("继续", markdown)
            self.assertNotIn("hidden", markdown)

    def test_session_filename_uses_ascii_slug_from_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "plain-project"
            project.mkdir()
            transcript = root / "codex.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:47:14.000Z",
                                "type": "session_meta",
                                "payload": {
                                    "id": "019e0544-7beb-7983-a458-de94206793f8",
                                    "timestamp": "2026-05-08T01:47:14.000Z",
                                    "cwd": str(project),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:48:30.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "Fix exporter bug"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("codex", transcript, config, cwd=str(project))

            self.assertEqual(result.markdown_path.name, "20260508-codex-fix-exporter-bug.md")

    def test_session_filename_uses_updated_date_and_removes_stale_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "plain-project"
            project.mkdir()
            transcript = root / "codex.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-08T01:47:14.000Z",
                                "type": "session_meta",
                                "payload": {
                                    "id": "019e0544-7beb-7983-a458-de94206793f8",
                                    "timestamp": "2026-05-08T01:47:14.000Z",
                                    "cwd": str(project),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-09T03:48:30.000Z",
                                "type": "response_item",
                                "payload": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{"type": "input_text", "text": "Fix exporter bug"}],
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            sessions_dir = root / "vault" / "AI Conversations" / "Projects" / "plain-project" / "sessions"
            sessions_dir.mkdir(parents=True)
            stale_note = sessions_dir / "20260508-codex-fix-exporter-bug.md"
            stale_note.write_text(
                "---\n"
                "session_id: 019e0544-7beb-7983-a458-de94206793f8\n"
                "---\n",
                encoding="utf-8",
            )

            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("codex", transcript, config, cwd=str(project))

            self.assertEqual(result.markdown_path.name, "20260509-codex-fix-exporter-bug.md")
            self.assertTrue(result.markdown_path.exists())
            self.assertFalse(stale_note.exists())

    def test_ascii_session_slug_drops_non_ascii_and_falls_back(self):
        self.assertEqual(ascii_slug("修复 codex hook", "session"), "codex-hook")
        self.assertEqual(ascii_slug("保存对话", "019e0544"), "019e0544")

    def test_title_slug_preserves_cjk_and_mixed_text(self):
        self.assertEqual(title_slug("Fix exporter bug", "fallback"), "fix-exporter-bug")
        self.assertEqual(title_slug("修复 codex hook", "fallback"), "修复-codex-hook")
        self.assertEqual(title_slug("保存对话", "019e0544"), "保存对话")
        self.assertEqual(
            title_slug("你和 AI 的对话，可能比答案更值钱", "fallback"),
            "你和-ai-的对话-可能比答案更值钱",
        )

    def test_title_slug_strips_filesystem_illegal_chars(self):
        self.assertEqual(
            title_slug('name with "quotes" and / slashes', "fallback"),
            "name-with-quotes-and-slashes",
        )

    def test_title_slug_falls_back_when_empty(self):
        self.assertEqual(title_slug("", "session"), "session")
        self.assertEqual(title_slug("???", "session"), "session")
        self.assertEqual(title_slug("///\\\\", "session"), "session")

    def test_title_slug_truncates_to_max_len(self):
        self.assertEqual(title_slug("a" * 100, "fallback", max_len=10), "a" * 10)
        # Truncation should not leave a trailing dash.
        self.assertEqual(title_slug("a-" * 50, "fallback", max_len=5), "a-a-a")

    def test_extract_claude_tool_usage_collects_tools_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "claude.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "text", "text": "I'll read it."},
                                    {"type": "tool_use", "name": "Read",
                                     "input": {"file_path": "/repo/a.py"}},
                                ]
                            },
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "tool_use", "name": "Bash",
                                     "input": {"command": "ls -la"}},
                                    {"type": "tool_use", "name": "Edit",
                                     "input": {"file_path": "/repo/a.py",
                                               "old_string": "x", "new_string": "y"}},
                                    {"type": "tool_use", "name": "Edit",
                                     "input": {"file_path": "/repo/b.py",
                                               "old_string": "p", "new_string": "q"}},
                                ]
                            },
                        }),
                        json.dumps({"type": "user", "message": {"content": "ok"}}),
                    ]
                ),
                encoding="utf-8",
            )
            usage = extract_claude_tool_usage(transcript)
            self.assertEqual(usage.tools, {"Read": 1, "Bash": 1, "Edit": 2})
            self.assertEqual(usage.files, ["/repo/a.py", "/repo/b.py"])
            self.assertEqual(usage.total_calls, 4)

    def test_extract_codex_tool_usage_handles_string_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "codex.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "payload": {
                                "type": "function_call",
                                "name": "shell",
                                "arguments": json.dumps({"command": ["ls"]}),
                            }
                        }),
                        json.dumps({
                            "payload": {
                                "type": "function_call",
                                "name": "read_file",
                                "arguments": json.dumps({"path": "/repo/x.py"}),
                            }
                        }),
                        json.dumps({
                            "payload": {
                                "type": "function_call",
                                "name": "read_file",
                                "arguments": "not-json",
                            }
                        }),
                    ]
                ),
                encoding="utf-8",
            )
            usage = extract_codex_tool_usage(transcript)
            self.assertEqual(usage.tools, {"shell": 1, "read_file": 2})
            self.assertEqual(usage.files, ["/repo/x.py"])

    def test_relativize_to_cwd_makes_paths_relative_when_possible(self):
        result = relativize_to_cwd(
            ["/repo/src/a.py", "/repo/src/b.py", "/other/c.py", "rel/d.py"],
            "/repo",
        )
        self.assertEqual(result, ["src/a.py", "src/b.py", "/other/c.py", "rel/d.py"])

    def test_relativize_to_cwd_passes_through_when_no_cwd(self):
        result = relativize_to_cwd(["/repo/a.py"], "")
        self.assertEqual(result, ["/repo/a.py"])

    def test_claude_assistant_with_inline_tool_use_is_marked_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "p"
            project.mkdir()
            transcript = root / "claude.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "type": "user",
                            "message": {"role": "user", "content": "请实现"},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:00:00Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {"role": "assistant", "content": [
                                {"type": "text", "text": "好的，我先读一下"},
                                {"type": "tool_use", "name": "Read",
                                 "input": {"file_path": str(project / "x.py")}},
                            ]},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:01:00Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {"role": "assistant", "content": [
                                {"type": "text", "text": "改完了，你看下方案"},
                            ]},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:02:00Z",
                        }),
                    ]
                ),
                encoding="utf-8",
            )
            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("claude", transcript, config, cwd=str(project))
            md = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("> [!action]- action", md)
            self.assertIn("> 好的，我先读一下", md)
            # Discussion message stays unboxed
            self.assertIn("\n改完了，你看下方案\n", md)
            # And exactly one action callout (not two)
            self.assertEqual(md.count("[!action]"), 1)

    def test_claude_assistant_text_then_separate_tool_use_marks_text_as_action(self):
        # Real Claude Code splits text and tool_use into separate assistant entries.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "p"
            project.mkdir()
            transcript = root / "claude.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "type": "user",
                            "message": {"role": "user", "content": "请实现"},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:00:00Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {"role": "assistant", "content": [
                                {"type": "text", "text": "好的，我先读一下 x.py"},
                            ]},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:01:00Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {"role": "assistant", "content": [
                                {"type": "tool_use", "name": "Read",
                                 "input": {"file_path": str(project / "x.py")}},
                            ]},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:01:30Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {"role": "assistant", "content": [
                                {"type": "text", "text": "改完了"},
                            ]},
                            "cwd": str(project), "sessionId": "s1",
                            "timestamp": "2026-05-08T01:02:00Z",
                        }),
                    ]
                ),
                encoding="utf-8",
            )
            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("claude", transcript, config, cwd=str(project))
            md = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("> [!action]- action\n> 好的，我先读一下 x.py", md)
            self.assertIn("\n改完了\n", md)
            self.assertEqual(md.count("[!action]"), 1)

    def test_codex_assistant_followed_by_function_call_is_marked_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "p"
            project.mkdir()
            transcript = root / "codex.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "timestamp": "2026-05-08T01:00:00Z",
                            "type": "session_meta",
                            "payload": {"id": "s1", "cwd": str(project),
                                        "timestamp": "2026-05-08T01:00:00Z"},
                        }),
                        json.dumps({
                            "timestamp": "2026-05-08T01:01:00Z",
                            "type": "response_item",
                            "payload": {"type": "message", "role": "user",
                                        "content": [{"type": "input_text", "text": "请帮我实现"}]},
                        }),
                        json.dumps({
                            "timestamp": "2026-05-08T01:02:00Z",
                            "type": "response_item",
                            "payload": {"type": "message", "role": "assistant",
                                        "content": [{"type": "output_text", "text": "好的，我先读一下"}]},
                        }),
                        json.dumps({
                            "timestamp": "2026-05-08T01:02:30Z",
                            "type": "response_item",
                            "payload": {"type": "function_call", "name": "shell",
                                        "arguments": json.dumps({"command": ["ls"]})},
                        }),
                        json.dumps({
                            "timestamp": "2026-05-08T01:03:00Z",
                            "type": "response_item",
                            "payload": {"type": "message", "role": "assistant",
                                        "content": [{"type": "output_text", "text": "结论是 X"}]},
                        }),
                    ]
                ),
                encoding="utf-8",
            )
            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("codex", transcript, config, cwd=str(project))
            md = result.markdown_path.read_text(encoding="utf-8")
            # First assistant (had a following function_call) is action
            self.assertIn("> [!action]- action\n> 好的，我先读一下", md)
            # Second assistant (no following function_call) stays as discussion
            self.assertIn("\n结论是 X\n", md)
            self.assertEqual(md.count("[!action]"), 1)

    def test_export_includes_related_files_and_tools_in_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "checkout"
            project.mkdir()
            transcript = root / "claude.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "type": "user",
                            "message": {"role": "user", "content": "请读 cli.py"},
                            "cwd": str(project),
                            "sessionId": "s1",
                            "timestamp": "2026-05-08T02:01:00.000Z",
                        }),
                        json.dumps({
                            "type": "assistant",
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {"type": "text", "text": "好的"},
                                    {"type": "tool_use", "name": "Read",
                                     "input": {"file_path": str(project / "cli.py")}},
                                ],
                            },
                            "cwd": str(project),
                            "sessionId": "s1",
                            "timestamp": "2026-05-08T02:02:00.000Z",
                        }),
                    ]
                ),
                encoding="utf-8",
            )
            config = ExportConfig(vault_dir=root / "vault", timezone="Asia/Singapore")
            result = export_transcript("claude", transcript, config, cwd=str(project))
            md = result.markdown_path.read_text(encoding="utf-8")
            self.assertIn("tool_call_count: 1", md)
            self.assertIn("tools_used:", md)
            self.assertIn("- Read", md)
            self.assertIn("related_files:", md)
            self.assertIn("- cli.py", md)

    def test_default_vault_dir_uses_documents_obsidian(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.dict("os.environ", {"AI_CONVO_VAULT": ""}):
                self.assertEqual(default_vault_dir(home), home / "Documents" / "obsidian")

    def test_merges_hooks_without_dropping_existing_config(self):
        command = "$HOME/.local/bin/ai-convo-exporter hook --provider claude"
        settings = {
            "env": {"A": "B"},
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 /Users/me/.claude/scripts/export-to-obsidian.py",
                            }
                        ]
                    }
                ]
            },
        }

        merged = merge_claude_settings(settings, command)
        merged_again = merge_claude_settings(merged, command)

        self.assertEqual(merged["env"], {"A": "B"})
        self.assertEqual(len(merged_again["hooks"]["Stop"]), 1)
        self.assertEqual(merged_again["hooks"]["Stop"][0]["hooks"][0]["command"], command)

    def test_merges_codex_hook_and_feature_flag(self):
        command = "$HOME/.local/bin/ai-convo-exporter hook --provider codex"
        hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}

        merged_hooks = merge_codex_hooks(hooks, command)
        merged_hooks_again = merge_codex_hooks(merged_hooks, command)
        config_toml = merge_codex_config_toml('model = "gpt-5.5"\n')
        legacy_config_toml = merge_codex_config_toml(
            "[features]\n"
            "codex_hooks = true\n"
            "hooks = false\n"
        )

        self.assertEqual(len(merged_hooks_again["hooks"]["Stop"]), 1)
        self.assertEqual(merged_hooks_again["hooks"]["Stop"][0]["hooks"][0]["command"], command)
        self.assertIn("[features]", config_toml)
        self.assertIn("hooks = true", config_toml)
        self.assertIn('model = "gpt-5.5"', config_toml)
        self.assertIn("hooks = true", legacy_config_toml)
        self.assertNotIn("codex_hooks", legacy_config_toml)
        self.assertEqual(legacy_config_toml.count("hooks = true"), 1)

    def test_merges_codex_writable_root_for_vault(self):
        from ai_convo_exporter.cli import merge_codex_config_toml

        config_toml = merge_codex_config_toml(
            'model = "gpt-5.5"\n\n'
            "[sandbox_workspace_write]\n"
            'writable_roots = ["/tmp/existing"]\n',
            "/Users/me/Obsidian Vault",
        )
        config_toml_again = merge_codex_config_toml(
            config_toml,
            "/Users/me/Obsidian Vault",
        )

        self.assertIn("[sandbox_workspace_write]", config_toml_again)
        self.assertIn('"/tmp/existing"', config_toml_again)
        self.assertEqual(config_toml_again.count('"/Users/me/Obsidian Vault"'), 1)


if __name__ == "__main__":
    unittest.main()
