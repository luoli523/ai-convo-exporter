# ai-convo-exporter

[English](README.md) | 简体中文

把 Codex 和 Claude Code 的对话记录导出到 Obsidian vault，并按项目维度组织。

导出器会为每段对话保留两份内容：

- 一份适合在 Obsidian 中阅读、搜索、打标签、做 Dataview 查询的 Markdown 笔记。
- 一份原始 JSONL transcript，保存在 `raw/` 目录下，方便以后重新解析或重新生成笔记。

## 目录结构

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

项目文件夹在多台机器之间保持稳定。只要当前 checkout 有 git remote，导出器会优先使用 remote path，例如 `luoli523/ads_attribution`，并转换成适合 Obsidian 文件夹使用的 slug，例如 `luoli523__ads-attribution`。如果没有 git remote，则退回使用当前目录名。

## 安装

在新 checkout 后直接执行：

```bash
./install.sh
```

指定 Obsidian vault：

```bash
./install.sh --vault "$HOME/Documents/Obsidian Vault"
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
  "vault_dir": "~/Documents/Obsidian Vault",
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
