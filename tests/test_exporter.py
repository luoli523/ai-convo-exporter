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
    merge_claude_settings,
    merge_codex_config_toml,
    merge_codex_hooks,
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
            self.assertEqual(result.markdown_path.name, "20260508-codex-019e0544.md")

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
