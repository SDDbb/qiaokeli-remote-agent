+++
project_name = "remote-agent"
category = "工具脚本 / 自动化类"
project_type = "可运行后台工具"
project_root = "/home/zhujintao/桌面/02-agent-tools/remote-agent"
primary_language = "Python"
tech_stack = ["Python 3", "Shell", "Syncthing", "Tailscale", "systemd", "OpenClaw", "Codex CLI", "ADB", "Android"]
entrypoints = [
  "systemctl --user enable --now qiaokeli-remote-agent.service",
  "systemctl --user enable --now qiaokeli-nexusdeck-api.service",
  "python3 scripts/remote_agent_api.py --pairing-json",
  "python3 scripts/remote_agent_submit.py --type status",
  "python3 scripts/remote_agent_status.py",
  "python3 scripts/android_control.py status",
  "python3 scripts/android_control.py current_app",
  "python3 scripts/remote_agent_submit.py --type android --android-action status",
  "python3 scripts/remote_agent_submit.py --type android --android-action open_url --url https://example.com",
  "qiaokeli-hybrid-run \"先让百炼执行，再让 Codex 审阅：...\"",
]
dependency_files = ["config.toml", "config/config.env.example", "config/tunnel_config.env.example"]
summary = "邮箱式个人远程 agent，接收 Syncthing 投递的命令，并把任务路由到 OpenClaw、Codex、browser playbook、Android ADB 控制层或 Bailian+Codex 混合链路；NexusDeck 是其 Android 手机端统一控制台。"
typical_tasks = ["维护后台 daemon 和 heartbeat", "调试远程 inbox/response 流程", "扩展 browser playbook、Android ADB 控制层或 hybrid 路由", "维护 NexusDeck API 与 Android App", "排查 tunnel、systemd 和命令超时"]
maturity = "中高，功能路径完整，但对本机路径、服务状态和外部协同工具依赖较重。"
status_hint = "项目已经把 tokensave / hybrid 流程写成明确工作约定，并支持结构化 browser playbook 与 Android ADB 控制命令。"
status = "active"
inference_notes = ["实际运行配置主要来自 ~/.config/qiaokeli-remote-agent/config.env。", "OpenClaw 基础设施已外迁到 openclaw-host。"]
+++

# remote-agent

## 项目作用

这是一个个人远程代理项目，核心形态是“邮箱式”后台 agent：手机或其他设备把命令写进共享目录，Fedora 主机上的 daemon 轮询后执行，再把结果写回 JSON。它既能跑自然语言任务，也能接收结构化命令、浏览器 playbook 和 Android ADB 控制任务。

## 主要技术栈

- Python 脚本
- shell 包装器
- Syncthing 文件传输
- Tailscale 私网访问
- systemd 用户服务
- OpenClaw / Codex CLI / Bailian 混合链路
- ADB / Android 手机控制

## 入口文件 / 启动方式

服务安装与启动：

```bash
systemctl --user daemon-reload
systemctl --user enable --now qiaokeli-remote-agent.service
```

本地测试：

```bash
python3 scripts/remote_agent_submit.py --type status
python3 scripts/remote_agent_status.py
python3 scripts/remote_agent_submit.py --type browser
python3 scripts/android_control.py status
python3 scripts/android_control.py current_app
python3 scripts/remote_agent_submit.py --type android --android-action status
```

混合执行：

```bash
qiaokeli-hybrid-run "先让百炼执行，再让 Codex 审阅：检查当前仓库 README 有没有明显问题，并给出最终结论。"
```

## 常用命令

```bash
systemctl --user enable --now qiaokeli-remote-agent.service
python3 scripts/remote_agent_submit.py --type status
python3 scripts/remote_agent_submit.py --type browser --playbook-file ./playbooks/example.com.json
python3 scripts/remote_agent_submit.py --type android --android-action screenshot
python3 scripts/remote_agent_submit.py --type android --android-action playbook --playbook-file ./playbooks/android_link_and_status.json
python3 scripts/remote_agent_status.py
bash start_tunnel.sh
```

## 关键目录结构说明

- `scripts/`: daemon、提交器、状态查看、browser playbook、Android ADB 控制、hybrid job 等核心逻辑
- `config/`: 示例配置和 tunnel 配置模板
- `systemd/`: 用户服务定义
- `nexusdeck-android/`: NexusDeck Android 原生控制台工程
- `playbooks/`: 可复用浏览器操作脚本
- `work_orders/`: 某些执行模式和流程设计说明
- `runtime/`: 运行期产物

## 未来维护时最可能做的事情

- 调整 mailbox 路由、超时、输出截断和心跳逻辑
- 扩展 browser playbook、Android 控制动作或 hybrid 审阅流程
- 维护 NexusDeck 手机端控制台和 `remote_agent_api.py`，把状态检查、任务提交、截图、文件传输和 playbook 入口收束到一个 APP
- 修复 Syncthing/Tailscale/服务状态联动问题
- 让 `tokensave` 流程支持更多工程类任务

## 风险与注意事项

- 强依赖本机绝对路径，例如共享目录、Codex/OpenClaw 可执行文件和默认工作目录
- Android 控制层依赖 ADB 授权；无线 ADB 应优先限制在可信局域网或 Tailscale 私网
- NexusDeck API 需要 Bearer token，绑定到 Tailscale IP 前应确认只在可信网络暴露
- 真正配置通常在 `~/.config/qiaokeli-remote-agent/config.env`，仓库中的示例文件只是模板
- 这是多系统协作项目，任何一环服务没起来，都会让整体“看似收单、实际不工作”
- `tunnel_config.env`、日志和 work order 里可能包含操作细节，写文档时要避免泄漏敏感路径或 token
- 与 `openhands-playground` 存在部分功能重叠，改动前要确认哪个是主线

## 当前成熟度判断

这已经是一个明确成形的个人自动化系统，不只是实验脚本；但它横跨文件同步、私网、宿主工具和多后端路由，稳定性高度依赖整套宿主环境同时正常。
