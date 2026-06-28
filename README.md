# Qiaokeli Remote Agent

**用手机遥控你的开发机上的 AI Agent。** 不在电脑前也能发任务、查状态、取结果。

```
手机 (Termux/NexusDeck) ──Syncthing──> Fedora 桌面 ──> AI Agent 执行 ──> 结果回传手机
                         Tailscale 私有网络 (安全,无需公网IP)
```

## 为什么需要

- 出门时想给 AI 发一个"帮我查下茅台今天 PE"——手机写一行字，桌面自动执行，结果回到手机
- 长任务跑着（训练、数据处理、照片回填），手机随时看进度
- 想用手机遥控桌面的浏览器（登录态的网页操作、抓数据）

核心设计：**Mailbox 模式**——不是实时 RPC，是异步任务信箱。手机投递任务 → 桌面 daemon 捡起来执行 → 结果写回共享文件夹 → 手机取走。断网也不丢任务。

## 技术栈

| 组件 | 作用 |
|---|---|
| Syncthing | 手机↔桌面文件同步（任务/结果双向传递） |
| Tailscale | 私有网络，手机在任何地方都能连到桌面 |
| Termux (Android) | 手机端的命令行执行环境 |
| NexusDeck (Android) | 可选：手机上的图形控制面板 |
| systemd 用户服务 | 桌面 daemon 托管，开机自启 |

AI 后端支持：Claude Code、Codex CLI、qiaokeli-cheap（省钱路由）。

> **历史变更**（2026-05-31）：旧的 hybrid/tokensave 流水线和 OpenClaw host 项目已归档到 `00-archive/`。当前远程 Agent 的后端已切换到 qiaokeli-cheap（独立 Python CLI）+ Codex + Claude Code。

## 共享文件夹结构

默认路径 `~/Sync/30_Projects/remote_agent/`：

```
commands/     ← JSON 结构化命令
inbox/        ← 自然语言任务（.txt/.md）
responses/    ← 执行结果
status/       ← heartbeat.json（桌面状态快照）
```

## 自然语言用法

在 `inbox/` 下丢一个文本文件：

```text
帮我查一下今天 NVIDIA 的股价，和半导体板块的整体走势。
```

daemon 会自动识别、路由到合适的 AI 后端执行，结果写入 `responses/` 同名的 `.json` 文件。

## 支持的命令类型

- `status` — 桌面状态快照
- `shell` — 执行 Shell 命令
- `codex` — Codex CLI 执行
- `browser` — Playwright 浏览器自动化
- `android` — ADB 手机控制
- `read_file` — 读取文件

## 快速开始

```bash
# 安装/更新服务
systemctl --user daemon-reload
systemctl --user enable --now qiaokeli-remote-agent.service

# 本地测试
python3 scripts/remote_agent_submit.py --type status
python3 scripts/remote_agent_status.py
```

## NexusDeck 手机控制面板

NexusDeck 是 Android 端的图形控制 App，通过 Tailscale 上的 HTTP API 与桌面通信。

启动桌面 API：
```bash
python3 scripts/remote_agent_api.py --pairing-json
systemctl --user enable --now qiaokeli-nexusdeck-api.service
```

构建 Android APK：
```bash
bash scripts/setup_nexusdeck_android_build_env.sh
bash nexusdeck-android/build-apk.sh
adb install -r nexusdeck-android/app/build/outputs/apk/debug/app-debug.apk
```

API 端点：
- `GET /api/v1/health` — 心跳
- `GET /api/v1/diagnostics` — 深度诊断（含 ADB 状态）
- `POST /api/v1/commands` — 提交命令
- `GET /api/v1/responses/<id>` — 取结果

## Android 设备控制

通过 ADB 控制手机。USB 初次配对后切无线 ADB：

```bash
adb tcpip 5555
adb connect <手机Tailscale IP>:5555

# 截图、UI树、点击、解锁…
python3 scripts/android_control.py status
python3 scripts/android_control.py screenshot
python3 scripts/android_control.py tap --x 540 --y 1800
```

## Browser Playbooks

对重复性的网页操作（登录后抓数据、提交表单），用声明式 Playbook 比通用 Agent 更可靠：

```json
{
  "steps": [
    {"action": "open", "url": "https://example.com"},
    {"action": "wait", "text": "Example Domain", "timeout_ms": 10000},
    {"action": "evaluate", "fn": "() => ({title: document.title})"}
  ]
}
```

## OpenHands 实时隧道

在手机上用 WebSocket 连接桌面 OpenHands CLI，实时远程 vibe coding：

```bash
# 桌面安装服务
systemctl --user enable --now qiaokeli-openhands-tunnel.service

# 手机 Termux 连接
pip install websockets
python scripts/simple_terminal_client.py ws://<tailscale-ip>:8765
```

## CHANGELOG

- **2026-05-31**: 旧的 hybrid/tokensave 流水线归档，后端切到 qiaokeli-cheap
- **2026-06**: 新增 NexusDeck API、browser playbook 引擎、OpenHands 隧道
