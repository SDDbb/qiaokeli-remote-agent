# NexusDeck Android 使用说明

NexusDeck 是 `remote-agent` 的 Android 手机端控制台。手机 App 通过 Tailscale 访问电脑上的 NexusDeck HTTP API，电脑侧 `remote-agent` daemon 收到命令后执行，再把结果写回；涉及手机自动化时，实际控制动作由电脑上已经授权的 ADB 完成。

当前链路可以理解为：

```text
手机 NexusDeck App -> Tailscale -> 电脑 NexusDeck API -> remote-agent commands -> daemon -> ADB -> 手机
```

## 适用场景

- 在手机上查看电脑端 agent 是否在线。
- 从手机发起 Codex、OpenClaw 或 hybrid 自然语言任务。
- 通过电脑 ADB 检查或控制手机，例如查看当前前台 App、截图、导出 UI 结构、打开 URL。
- 从手机上传文件到电脑项目的运行目录，或读取电脑上的指定文件。

## 使用前准备

电脑侧需要满足这些条件：

1. 电脑和手机都已经接入同一个 Tailscale 网络。
2. 电脑端 `qiaokeli-remote-agent.service` 正常运行。
3. 电脑端 NexusDeck API 正常运行，并监听电脑的 Tailscale 地址。
4. 电脑上的 ADB 已经能看到并控制目标手机。

常用检查命令：

```bash
systemctl --user status qiaokeli-remote-agent.service
systemctl --user status qiaokeli-nexusdeck-api.service
python3 scripts/remote_agent_api.py --pairing-json
python3 scripts/android_control.py status
```

如果 API 还只监听 `127.0.0.1`，手机无法访问。需要在电脑的 `~/.config/qiaokeli-remote-agent/config.env` 里配置：

```dotenv
NEXUSDECK_API_BIND_HOST=<电脑的 Tailscale IP>
NEXUSDECK_API_PORT=8765
```

然后重启 API：

```bash
systemctl --user restart qiaokeli-nexusdeck-api.service
```

不要把真实 token、手机解锁 PIN 或私有配置写进仓库文档。

## 安装 App

开发调试安装：

```bash
bash scripts/setup_nexusdeck_android_build_env.sh
bash nexusdeck-android/build-apk.sh
~/.local/opt/platform-tools/adb install -r nexusdeck-android/app/build/outputs/apk/debug/app-debug.apk
```

安装后打开手机上的 NexusDeck。

## 首次配对

在电脑项目根目录运行：

```bash
python3 scripts/remote_agent_api.py --pairing-json
```

它会输出类似：

```json
{
  "base_url": "http://<电脑的 Tailscale IP>:8765",
  "token": "<Bearer token>"
}
```

在手机 App 的 `Settings` 页填写：

- `Base URL`：上面的 `base_url`
- `Bearer token`：上面的 `token`
- `Work mode`：建议日常先用 `confirm` 或 `whitelist`
- `Agent permission`：建议日常先用 `Workspace`，需要完全接管电脑时再切到 `Full Access` 或 `Bypass`

点 `Save` 保存。保存后可以回到 `Deck` 页点 `Refresh` 验证连接。

也可以用 intent 写入配置，适合开发时快速重装后恢复设置：

```bash
adb shell am start \
  -n com.qiaokeli.nexusdeck/.MainActivity \
  --es nexus_base_url "http://<电脑的 Tailscale IP>:8765" \
  --es nexus_token "<Bearer token>" \
  --ez nexus_refresh true
```

## 工作模式

`Settings` 页里的 `Work mode` 会随每次命令一起提交给电脑 API。

- `plan`：只生成计划，不真正落地执行命令。
- `confirm`：默认推荐模式；高风险命令需要额外确认。
- `whitelist`：只允许安全命令和白名单内的 playbook。
- `bypass`：跳过确认，适合可信环境下的临时调试；谨慎使用。

当前手机界面还没有为高风险命令做二次确认弹窗，所以日常建议优先使用 `confirm` 或 `whitelist`，把 `bypass` 留给你明确知道自己在做什么的时候。

## Deck 页

`Deck` 是系统总览页。

- `Refresh`：请求 `/api/v1/health`，做轻量健康检查，只确认 API、电脑 host 和能力列表，不再同步等待 ADB。
- `Diagnostics`：请求 `/api/v1/diagnostics`，做深度检查，会额外跑 ADB status，可能比 `Refresh` 慢。
- `Playbooks`：列出电脑项目 `playbooks/` 下可用的 playbook。
- `Last Task`：查询上一次提交命令的状态。

如果 `Health` 面板里 ADB 报错，说明电脑能收到 App 请求，但电脑到手机的 ADB 这段链路还有问题。

## Agent 页

`Agent` 页用于从手机向电脑 agent 提交自然语言任务。

1. 在 `Message` 输入框写任务。
2. 选择后端：`Codex`、`OpenClaw`、`Hybrid`、`Claude Code` 或 `DeepSeek`。
3. 点 `Send`。
4. App 会先显示已提交的 command id，然后自动轮询最终结果。

不同后端的适合场景：

- `Codex`：本机 Codex CLI，当前默认走 `gpt-5.5`；适合代码、仓库分析、文件修改类任务。
- `OpenClaw`：桌面 OpenClaw 工作流入口，适合调用你电脑上已经配置好的本地自动化流程。
- `Hybrid`：混合链路，先让低成本/外部 worker 出草稿，再交给本机 Codex 复核，适合需要“便宜初稿 + 高质量复核”的任务。
- `Claude Code`：Claude Code CLI 入口。电脑上需要先安装并登录 `claude` 或把 `CLAUDE_BIN` 配到正确命令，否则会返回清晰的失败信息。
- `DeepSeek`：走本机 `qiaokeli-cheap`，适合摘要、初稿、分类、翻译和其他低成本草稿任务。

`OpenClaw` 和 `Hybrid` 不是模型名，而是电脑端执行路线：前者偏本机自动化工作流，后者偏多模型协作流程。

### Agent 权限档位

`Settings` 页的 `Agent permission` 会随 `Codex`、`Hybrid` 和 `Claude Code` 任务一起提交。手机端可以选择档位，电脑端还会用 `QIAOKELI_REMOTE_AGENT_MAX_AGENT_PERMISSION` 再做一次上限限制。

- `Default`：使用 CLI 自己的默认权限行为。
- `Read Only`：Codex 使用 read-only sandbox，适合只检查、不改文件。
- `Workspace`：Codex 使用 workspace-write sandbox，适合日常改项目内文件。
- `Full Access`：Codex 使用 danger-full-access sandbox，适合你明确要让它操作工作区外资源的时候。
- `Bypass`：Codex 使用 bypass approvals and sandbox，风险最高，只适合短时间可信调试。

当前这台电脑的运行配置允许最高到 `Bypass`；仓库模板默认建议最高只到 `Workspace`。

## Phone 页

`Phone` 页用于通过电脑 ADB 控制手机。这里的控制不是 App 自己申请无障碍权限，而是电脑端执行 ADB 命令。

常用按钮：

- `Status`：查看 ADB 设备状态。
- `Screenshot`：让电脑通过 ADB 截图，结果通常会返回 artifact 路径。
- `Current App`：查看手机当前前台包名和 Activity。
- `UI Dump`：导出当前界面的 UI 层级，适合后续自动化分析。
- `Open URL On Phone`：在手机上打开输入框里的 URL。

推荐第一次验证顺序：

1. 点 `Status`，确认 ADB 通。
2. 点 `Current App`，确认能读到当前前台 App。
3. 在 URL 输入框填 `https://example.com`，点 `Open URL On Phone`。
4. 看 `Result` 面板最终是否出现 `completed` / `ok: true` 之类结果，并确认手机浏览器打开页面。

提交后 App 会自动等待电脑 daemon 的最终响应。正常情况下，`Result` 面板会从 `accepted` 更新为最终 JSON。

## Files 页

`Files` 页提供手机和电脑之间的轻量文件入口。

- `Read Computer File`：读取电脑上的指定文件路径，并通过 `read_file` 命令返回内容。
- `Upload Phone File`：从手机文件选择器选一个文件，上传到电脑项目的 `runtime/nexusdeck/uploads/` 目录。

上传已经改为流式上传，适合中等视频文件；电脑端默认限制最大 `200 MB`，上传结果只返回 `artifact_id` 和文件名，不再把电脑绝对路径暴露给手机。

读取电脑文件现在由电脑端 `QIAOKELI_REMOTE_AGENT_READ_FILE_ROOTS` 限制可读目录。默认只建议读项目目录和 remote-agent 共享目录，不要把 `.env`、token、PIN 或私有配置复制进结果或文档。

## 结果怎么看

界面底部有两个输出面板：

- `Health`：最近一次 `Refresh` 的健康检查结果。
- `Result`：最近一次按钮或任务提交的结果。

常见状态：

- `accepted`：API 已经把命令写入 `commands/`，等待 daemon 执行。
- `completed`：daemon 已执行完成。
- `failed` 或 `ok: false`：命令执行失败，需要看 JSON 里的 `error` 字段。
- `unknown`：API 没找到对应命令或响应文件，可能是 command id 不对、daemon 没启动，或共享目录状态异常。

## 故障排查

连接失败：

```bash
systemctl --user status qiaokeli-nexusdeck-api.service
python3 scripts/remote_agent_api.py --pairing-json
```

- 确认手机 Tailscale 在线。
- 确认 `Base URL` 是 `http://<电脑的 Tailscale IP>:8765`，不是 `127.0.0.1`。
- 确认 token 没填错。

返回 `401`：

- Bearer token 不匹配。
- 重新在电脑运行 `python3 scripts/remote_agent_api.py --pairing-json`，把 token 填回 App。

一直停在 `accepted`：

```bash
systemctl --user status qiaokeli-remote-agent.service
journalctl --user -u qiaokeli-remote-agent.service -n 80 --no-pager
```

- daemon 可能没有运行。
- daemon 可能还在旧代码里，重启服务后再试。
- 命令文件已经写入，但响应文件没有生成。

ADB 相关失败：

```bash
adb devices
python3 scripts/android_control.py status
python3 scripts/android_control.py current_app
```

- 手机需要允许 USB 调试或无线调试授权。
- 手机锁屏时，部分截图、UI dump 或打开页面动作可能不完整。
- 如果电脑连着多台 Android 设备，先确认 ADB 当前目标设备正确。

打开 URL 没反应：

- 先用 `Current App` 确认 ADB 能读到前台 App。
- 再在电脑上直接跑：

```bash
python3 scripts/android_control.py open_url --url https://example.com
```

如果电脑命令成功但 App 不成功，优先检查 API、daemon 和 command response。

## 安全提醒

- NexusDeck API 必须使用 Bearer token。
- API 只应暴露在可信网络，例如 Tailscale；不要直接暴露到公网。
- 不要把真实 token、PIN、生产数据或私有路径写进 README、USAGE 或索引文件。
- `bypass` 模式和高风险 Android 动作只在短时间调试时使用。
- ADB 授权只给你自己的可信设备。
