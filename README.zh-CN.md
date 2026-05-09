# ai-convo-exporter

[English](README.md) | 简体中文

把 Codex 和 Claude Code 的对话记录导出到 Obsidian vault，并按项目维度组织。

导出器会为每段对话保留两份内容：

- 一份适合在 Obsidian 中阅读、搜索、打标签、做 Dataview 查询的 Markdown 笔记。
- 一份原始 JSONL transcript，保存在 `raw/` 目录下，方便以后重新解析或重新生成笔记。

## 目录结构

```text
~/Documents/obsidian/
  AI Conversations/
    Daily/
      2026-05-08.md                              # 当日所有 session 的汇总，一行一条
    Projects/
      ads_attribution/
        _index.md
        sessions/
          20260508-codex-保存对话.md            # 中文 / Unicode 标题完整保留
        raw/
          codex/
            019e0544-7beb-7983-a458-de94206793f8.jsonl
          claude/
            fd7d3855-0b5d-482d-a008-0827ab6cd875.jsonl
```

项目文件夹直接使用短项目名。只要当前 checkout 有 git remote，导出器会取仓库名，例如从 `luoli523/ads_attribution` 得到 `ads_attribution`。如果没有 git remote，则退回使用当前目录名。Session 笔记文件名使用 `YYYYMMDD-[codex|claude]-<title-slug>.md`，slug 会保留 CJK / Unicode 字符，只把标点和空白规范化成 `-`。

## Session 笔记里有什么

每篇 session 笔记的 frontmatter 信息丰富，Obsidian 的 Dataview 可以直接查询：

```yaml
type: ai-conversation
provider: claude
session_id: 5a7c7cb2-...
project: ai-convo-exporter
project_slug: ai-convo-exporter
created: 2026-05-09T15:25:48+08:00
updated: 2026-05-09T18:35:15+08:00
cwd: /Users/me/work/ai-convo-exporter
git_repo: https://github.com/luoli523/ai-convo-exporter.git
git_branch: feat/enrich-markdown
machine: my-laptop
raw_transcript: ../raw/claude/5a7c7cb2-....jsonl
tool_call_count: 171
tools_used: [Bash, Edit, Read, TaskCreate, ToolSearch]
related_files: [src/ai_convo_exporter/cli.py, tests/test_exporter.py, README.md]
related_sessions: ["[[20260507-claude-vault-detection]]"]
decision_count: 11
tags: [ai/conversation, provider/claude, project/ai-convo-exporter]
```

正文开头是 TL;DR 摘要（主题、讨论/实现轮次、涉及文件、决策数），接下来是对话内容。纯操作性的 assistant 消息（执行工具、叙述文件改动等）会被包进折叠的 `> [!action]-` callout，复读时不抢主视觉。包含决策性短语（"我建议"、"decision:"、"let's go with" 等）的消息会被加上 `> [!decision]+` 标记。

Daily/ 目录下的笔记每次导出都会更新，按当日逐条列出 session 的 [[wiki 链接]]。这样 Obsidian 的 Daily Notes / Periodic Notes 工作流可以自然地把 AI 工作和当日笔记汇总在一起。

## 安装

在新 checkout 后直接执行：

```bash
./install.sh
```

指定 Obsidian vault：

```bash
./install.sh --vault "$HOME/Documents/obsidian"
```

安装并导入本机历史 transcript：

```bash
./install.sh --backfill
```

只预览将要修改的内容，不写入配置：

```bash
./install.sh --dry-run
```

安装脚本会做这些事：

- 创建 `~/.config/ai-convo-exporter/config.json`。
- 在 `~/.local/bin/ai-convo-exporter` 安装命令包装器。
- 向 `~/.claude/settings.json` 添加 Claude Code `Stop` hook。
- 向 `~/.codex/hooks.json` 添加 Codex `Stop` hook。
- 在 `~/.codex/config.toml` 中通过 `[features] hooks = true` 启用 Codex hooks。
- 把 Obsidian vault 加入 Codex 的 `sandbox_workspace_write.writable_roots`，让 hook 在 workspace-write 模式下也能写入笔记。

安装是幂等的。重复执行 `./install.sh` 会更新同一份 hook 配置，不会重复追加多份 hook。

## 命令

```bash
ai-convo-exporter hook --provider codex
ai-convo-exporter hook --provider claude
ai-convo-exporter export ~/.codex/sessions/.../rollout.jsonl --provider codex
ai-convo-exporter scan
ai-convo-exporter backfill
ai-convo-exporter doctor
```

## 配置

配置文件位置：

```text
~/.config/ai-convo-exporter/config.json
```

可用环境变量：

- `AI_CONVO_VAULT`：Obsidian vault 路径。
- `AI_CONVO_CONFIG`：配置文件路径。
- `AI_CONVO_TIMEZONE`：安装脚本使用的默认时区。

默认配置：

```json
{
  "vault_dir": "~/Documents/obsidian",
  "conversations_dir": "AI Conversations",
  "timezone": "Asia/Singapore",
  "machine": "hostname",
  "archive_raw": true
}
```

## 工作方式

Claude Code 和 Codex 都会在每轮对话结束时触发 `Stop` hook。hook 会把当前 transcript 路径传给 `ai-convo-exporter`，导出器再解析 JSONL、生成 Markdown，并把原始 JSONL 复制到 vault。

如果 hook 没有执行，或者你想导入旧记录，可以手动运行：

```bash
ai-convo-exporter backfill
```

`backfill` 会扫描默认位置：

- Claude Code：`~/.claude/projects/**/*.jsonl`
- Codex：`~/.codex/sessions/**/*.jsonl`
- Codex archived sessions：`~/.codex/archived_sessions/*.jsonl`

## 开发

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

项目只使用 Python 标准库，不需要第三方依赖。
