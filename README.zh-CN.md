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

项目文件夹直接使用短项目名。只要当前 checkout 有 git remote，导出器会取仓库名，例如从 `luoli523/ads_attribution` 得到 `ads_attribution`。如果没有 git remote，则退回使用当前目录名。Session 笔记文件名使用 `YYYYMMDD-[codex|claude]-[ascii-session-name].md`，其中 `YYYYMMDD` 是 session 最后更新时间。非 ASCII 标题文本会被丢弃，如果清理后为空则退回使用 session id 前缀。

## 安装

### 推荐：pipx（无需 clone）

```bash
pipx install git+https://github.com/luoli523/ai-convo-exporter
ai-convo-exporter setup
```

`pipx` 会把 `ai-convo-exporter` 装进独立的 venv 并放进 PATH。
`setup` 会自动检测 Obsidian vault、写入 `~/.config/ai-convo-exporter/config.json`，
并为 Codex 和 Claude Code 注册 Stop hook。

卸载：`pipx uninstall ai-convo-exporter`。

### 备选：pip --user

```bash
pip install --user git+https://github.com/luoli523/ai-convo-exporter
ai-convo-exporter setup
```

（Homebrew Python 上可能撞 PEP 668，建议优先用 pipx。）

### 源码安装 / 开发用

```bash
git clone https://github.com/luoli523/ai-convo-exporter
cd ai-convo-exporter
./install.sh
```

`./install.sh` 会在 `~/.local/bin/ai-convo-exporter` 创建一个 bash 包装器
指向当前 checkout，然后执行 `setup`。如果 PATH 中已经存在 `ai-convo-exporter`
（例如先前用 pipx 装过），脚本会跳过包装器创建，避免覆盖已有命令。

### Setup 选项

`setup`（以及 `./install.sh`）支持相同的参数：

```bash
ai-convo-exporter setup --vault "$HOME/Documents/obsidian"   # 跳过检测
ai-convo-exporter setup --dry-run                            # 仅预览
./install.sh --backfill                                      # 顺便补导历史
```

不传 `--vault` 时，`setup` 会读取 Obsidian 的 vault 注册表
（macOS：`~/Library/Application Support/obsidian/obsidian.json`，
Linux：`~/.config/obsidian/obsidian.json`）并交互式让你选择：

- 只有一个 vault → `[Y/n/m]` 确认（`m` 进入手动输入路径）。
- 多个 vault → 按"当前打开"和"最近使用"排序后编号列出，输入 `m` 手动输入路径。
- Obsidian 没装或从未打开过 → 提示安装/打开 Obsidian 后退出，不做任何修改。

`setup` 是幂等的。Hook 配置就地更新，不会重复追加。重复执行且不传 `--vault` 时，上次配置的 vault 会在选择列表中标记 `[current]` 并作为默认选项。

`setup` 会写入：

- `~/.config/ai-convo-exporter/config.json`
- `~/.claude/settings.json` 中的 Claude Code `Stop` hook
- `~/.codex/hooks.json` 中的 Codex `Stop` hook
- `~/.codex/config.toml` 中的 `[features] hooks = true`
- 把 vault 路径加入 Codex 的 `sandbox_workspace_write.writable_roots`，让 hook 在 workspace-write 模式下也能写入。

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
