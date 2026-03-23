#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.client
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


OPENCLAW_ENV_PATH = Path.home() / ".openclaw" / ".env"
DEFAULT_BAILIAN_BASE_URL = "https://coding.dashscope.aliyuncs.com/v1"
DEFAULT_BAILIAN_MODEL = "qwen3-coder-plus"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n...[truncated]..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Background Bailian+Codex job for qiaokeli remote agent")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--response-file", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--openclaw-bin", required=True)
    parser.add_argument("--openclaw-agent", required=True)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--max-output-chars", type=int, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--input-mode", required=True)
    return parser.parse_args()


def load_openclaw_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not OPENCLAW_ENV_PATH.exists():
        return values
    for raw_line in OPENCLAW_ENV_PATH.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def parse_openclaw_text(raw: str) -> str:
    outer = json.loads(raw)
    payloads = outer.get("result", {}).get("payloads", [])
    first = payloads[0] if payloads else {}
    return str(first.get("text", "")).strip()


def parse_json_object(text: str) -> dict[str, object]:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3:
            body = "\n".join(lines[1:-1]).strip()
    return json.loads(body)


def maybe_override_classification(prompt: str, parsed: dict[str, object]) -> dict[str, object]:
    lowered = prompt.lower()
    patch_signals = [
        "改哪些文件",
        "代码修改",
        "补丁",
        "patch",
        "修复",
        "bug",
        "实现",
        "重构",
        "apply",
        "测试草案",
        "给出代码修改草案",
    ]
    research_signals = [
        "总结差异",
        "对比",
        "研究",
        "调研",
        "阅读",
        "分析",
    ]
    if any(token in prompt for token in patch_signals) or any(token in lowered for token in patch_signals):
        parsed["mode"] = "patch"
        parsed["review_profile"] = "strict"
        if "preferred_backend" not in parsed:
            parsed["preferred_backend"] = "direct_bailian"
    elif parsed.get("mode") == "patch" and any(token in prompt for token in research_signals):
        parsed["review_profile"] = "strict"
    elif parsed.get("mode") == "patch":
        parsed["review_profile"] = "strict"
    return parsed


def bailian_chat_completion(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1600,
    temperature: float = 0.2,
) -> str:
    env = load_openclaw_env()
    api_key = os.environ.get("CODING_PLAN_API_KEY") or env.get("CODING_PLAN_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing CODING_PLAN_API_KEY for direct Bailian call")
    base_url = os.environ.get("QIAOKELI_DIRECT_BAILIAN_BASE_URL", DEFAULT_BAILIAN_BASE_URL).rstrip("/")
    payload = {
        "model": os.environ.get("QIAOKELI_DIRECT_BAILIAN_MODEL", model or DEFAULT_BAILIAN_MODEL),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="ignore")
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Direct Bailian HTTP {exc.code}: {detail[:600]}") from exc
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError) as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError(f"Direct Bailian connection failed: {exc}") from exc
            time.sleep(1.2 * (attempt + 1))
    else:
        raise RuntimeError(f"Direct Bailian connection failed: {last_error}")

    body = json.loads(raw)
    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError("Direct Bailian returned no choices")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        content = "\n".join(parts)
    return str(content).strip()


def classify_tokensave_mode(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    classifier_prompt = f"""You are the task classifier for a coding orchestration stack.
Return strict JSON only with this exact shape:
{{
  "mode": "brief|patch|research|general",
  "engineering_context": "new_project|bugfix|maintenance|none",
  "preferred_backend": "direct_bailian|openclaw_bailian",
  "review_profile": "light|standard|strict",
  "needs_tools": true,
  "confidence": 0.0,
  "reason": "...",
  "review_focus": ["...", "..."]
}}

Rules:
- language: Simplified Chinese
- classify conservatively
- brief: social/project brief, progress update, README-style summary, weekly/daily report
- patch: code changes, bug fixes, implementation, tests, refactors, scripts
- research: repo reading, multi-file analysis, comparison, investigation, strategy/research notes
- general: if the task does not fit the above clearly
- new_project: asks to scaffold/build/design a new project or module from scratch
- bugfix: asks to debug, locate root cause, fix an error, or repair a broken feature
- maintenance: asks to tidy, refactor, upgrade, reorganize, add docs/tests without a clear bug
- none: not an engineering workflow
- choose direct_bailian for pure text drafting/classification/summarization tasks
- choose openclaw_bailian if the task likely needs agent memory, browser tools, project workspace context, or external tool coupling
- if the task mentions browsing, websites, OpenClaw, social posting, file-system operation, service status, or concrete local repo paths, prefer openclaw_bailian
- choose light review for low-risk brief/general drafting tasks
- choose standard review for most research tasks
- choose strict review for patch/code/system-risk tasks
- do not claim anything was executed

User task:
{prompt}

Execution working directory:
{args.workdir}
"""
    try:
        content = bailian_chat_completion(
            DEFAULT_BAILIAN_MODEL,
            [
                {"role": "system", "content": "You are a strict JSON classifier."},
                {"role": "user", "content": classifier_prompt},
            ],
            max_tokens=900,
            temperature=0.1,
        )
        parsed = parse_json_object(content)
        parsed["classifier_backend"] = "direct_bailian"
    except Exception:
        completed = subprocess.run(
            [
                args.openclaw_bin,
                "agent",
                "--agent",
                args.openclaw_agent,
                "--json",
                "--timeout",
                "120",
                "--message",
                classifier_prompt,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=150,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Bailian classifier failed")
        parsed = parse_json_object(parse_openclaw_text(completed.stdout))
        parsed["classifier_backend"] = "openclaw_bailian"
    mode = str(parsed.get("mode", "general")).strip().lower()
    if mode not in {"brief", "patch", "research", "general"}:
        mode = "general"
    parsed["mode"] = mode
    context = str(parsed.get("engineering_context", "none")).strip().lower()
    if context not in {"new_project", "bugfix", "maintenance", "none"}:
        context = "none"
    parsed["engineering_context"] = context
    backend = str(parsed.get("preferred_backend", "direct_bailian")).strip().lower()
    if backend not in {"direct_bailian", "openclaw_bailian"}:
        backend = "direct_bailian"
    parsed["preferred_backend"] = backend
    review_profile = str(parsed.get("review_profile", "standard")).strip().lower()
    if review_profile not in {"light", "standard", "strict"}:
        review_profile = "standard"
    parsed["review_profile"] = review_profile
    return maybe_override_classification(prompt, parsed)


def build_worker_prompt(prompt: str, classification: dict[str, object]) -> str:
    mode = str(classification.get("mode", "general"))
    engineering_context = str(classification.get("engineering_context", "none"))
    mode_specific_rules = {
        "brief": """当前任务模式是 brief。
- 优先产出项目简报、进展摘要、可发知乎/Reddit/GitHub 的文案底稿
- proposed_file_changes 应优先指向 README、brief、notes、memory、social draft
- proposed_reply 应偏向最终可读简报
""",
        "patch": """当前任务模式是 patch。
- 优先产出代码修改草案、测试建议、受影响文件列表
- proposed_commands 应偏向 lint/test/grep/py_compile 等验证命令
- proposed_file_changes 应明确到具体文件或目录
""",
        "research": """当前任务模式是 research。
- 优先产出阅读计划、调查路径、证据清单、研究笔记结构
- proposed_file_changes 应优先指向 notes、reports、research outputs、memory
- proposed_reply 应偏向研究结论或调查摘要
""",
        "general": """当前任务模式是 general。
- 维持保守的通用任务拆解，不要过度承诺
""",
    }[mode]

    engineering_rules = {
        "new_project": """当前工程语境是 new_project。
- execution_intent 默认优先考虑 plan_only 或 apply_patch
- files_to_check 应关注现有仓库边界、README、配置、骨架位置
- proposed_changes 应偏向新目录、新模块、README、配置样板、测试骨架
- verification_steps 应偏向 py_compile、pytest、lint、最小运行验证
""",
        "bugfix": """当前工程语境是 bugfix。
- execution_intent 默认优先考虑 apply_patch
- files_to_check 要尽量列出根因排查入口、调用链文件、相关配置和测试
- proposed_changes 要强调最小修复面和回归风险
- verification_steps 必须包含至少一个回归验证步骤
""",
        "maintenance": """当前工程语境是 maintenance。
- execution_intent 可为 plan_only 或 apply_patch
- files_to_check 应覆盖整理、重构、文档或测试所涉及的真实文件
- verification_steps 应包含静态检查或目录核对
""",
        "none": """当前工程语境不是明确的工程施工任务。
- 保持保守，不要虚构可执行改动
""",
    }[engineering_context]

    return f"""You are the low-cost execution worker in a coding orchestration stack.
Return strict JSON only with this exact shape:
{{
  "mode": "brief|patch|research|general",
  "engineering_context": "new_project|bugfix|maintenance|none",
  "task_summary": "...",
  "risk_level": "low|medium|high",
  "execution_intent": "plan_only|apply_patch|tool_exec",
  "recommended_route": "bailian_only|bailian_then_codex|codex_only",
  "files_to_check": ["...", "..."],
  "proposed_changes": ["...", "..."],
  "verification_steps": ["...", "..."],
  "execution_draft": {{
    "goal": "...",
    "plan": ["...", "..."],
    "proposed_commands": ["..."],
    "proposed_file_changes": ["..."],
    "proposed_reply": "...",
    "risks": ["..."],
    "needs_human_confirmation": true
  }}
}}

Rules:
- language: Simplified Chinese
- do not invent local command outputs
- this is a planning and draft layer only
- do not claim code was modified
- if the task is risky, say so clearly
- when the task says "当前目录/current directory", it refers to the execution working directory below
- prefer repo-relative paths when possible; otherwise use the explicit working directory

上游分类结果：
{json.dumps(classification, ensure_ascii=False, indent=2)}

Execution working directory:
{classification.get("execution_workdir", "")}

{mode_specific_rules}
{engineering_rules}

User task:
{prompt}
"""


def run_direct_bailian_worker(prompt: str, worker_prompt: str, classification: dict[str, object]) -> dict[str, object]:
    content = bailian_chat_completion(
        DEFAULT_BAILIAN_MODEL,
        [
            {"role": "system", "content": "You are a strict JSON task planner."},
            {"role": "user", "content": worker_prompt},
        ],
        max_tokens=2200,
        temperature=0.2,
    )
    parsed = parse_json_object(content)
    parsed["mode"] = classification.get("mode", "general")
    parsed["classification"] = classification
    parsed["engineering_context"] = classification.get("engineering_context", "none")
    return parsed


def run_openclaw_bailian_worker(args: argparse.Namespace, worker_prompt: str, classification: dict[str, object]) -> dict[str, object]:
    completed = subprocess.run(
        [
            args.openclaw_bin,
            "agent",
            "--agent",
            args.openclaw_agent,
            "--json",
            "--timeout",
            str(max(120, args.timeout - 90)),
            "--message",
            worker_prompt,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(150, args.timeout - 60),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "OpenClaw Bailian worker failed")
    parsed = parse_json_object(parse_openclaw_text(completed.stdout))
    parsed["mode"] = classification.get("mode", "general")
    parsed["classification"] = classification
    parsed["engineering_context"] = classification.get("engineering_context", "none")
    return parsed


def run_bailian_worker(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    classification = classify_tokensave_mode(args, prompt)
    classification["execution_workdir"] = args.workdir
    worker_prompt = build_worker_prompt(prompt, classification)
    backend = str(classification.get("preferred_backend", "direct_bailian"))
    if backend == "openclaw_bailian":
        parsed = run_openclaw_bailian_worker(args, worker_prompt, classification)
    else:
        try:
            parsed = run_direct_bailian_worker(prompt, worker_prompt, classification)
        except Exception:
            parsed = run_openclaw_bailian_worker(args, worker_prompt, classification)
            backend = "openclaw_bailian"
    parsed["worker_backend"] = backend
    return parsed


def run_codex_review(args: argparse.Namespace, prompt: str, worker_output: dict[str, object]) -> dict[str, object]:
    mode = str(worker_output.get("mode", "general")).strip().lower()
    engineering_context = str(worker_output.get("engineering_context", "none")).strip().lower()
    review_profile = str(worker_output.get("classification", {}).get("review_profile", "standard")).strip().lower()

    profile_instructions = {
        "light": """当前审阅档位是 light。
- 只做轻量一致性检查
- 重点确认模式是否匹配、是否有明显编造、最终回复是否可直接给用户
- 优先输出简洁 final_reply，避免重复转述整个草案
""",
        "standard": """当前审阅档位是 standard。
- 做正常质量审阅
- 检查结论是否建立在草案事实上
- 保持 final_reply 简洁，但允许指出明显缺口
""",
        "strict": """当前审阅档位是 strict。
- 做严格工程审阅
- 明确指出证据不足、文件范围不清、命令或改动不可直接采信的地方
- 对代码、补丁、系统任务保持保守，不要轻易 approve
""",
    }[review_profile]

    if review_profile == "light":
        review_payload = {
            "mode": worker_output.get("mode", "general"),
            "task_summary": worker_output.get("task_summary", ""),
            "risk_level": worker_output.get("risk_level", ""),
            "task_reason": worker_output.get("classification", {}).get("reason", ""),
            "proposed_reply": worker_output.get("execution_draft", {}).get("proposed_reply", ""),
            "risks": worker_output.get("execution_draft", {}).get("risks", []),
        }
    elif review_profile == "standard":
        review_payload = {
            "mode": worker_output.get("mode", "general"),
            "task_summary": worker_output.get("task_summary", ""),
            "risk_level": worker_output.get("risk_level", ""),
            "classification": worker_output.get("classification", {}),
            "execution_draft": {
                "goal": worker_output.get("execution_draft", {}).get("goal", ""),
                "plan": worker_output.get("execution_draft", {}).get("plan", []),
                "proposed_reply": worker_output.get("execution_draft", {}).get("proposed_reply", ""),
                "risks": worker_output.get("execution_draft", {}).get("risks", []),
            },
        }
    else:
        review_payload = worker_output

    reviewer_prompt = f"""Review the following Bailian execution draft for the user task.
Reply in strict JSON only with this exact shape:
{{
  "verdict": "approve|revise|reject",
  "final_reply": "...",
  "review_notes": ["..."],
  "safe_next_steps": ["..."],
  "approved_execution_intent": "plan_only|apply_patch|tool_exec",
  "approved_files_to_check": ["...", "..."],
  "approved_proposed_changes": ["...", "..."],
  "approved_verification_steps": ["...", "..."]
}}

Rules:
- language: Simplified Chinese
- be concise and concrete
- this is a pre-execution review step, not a post-execution audit
- do not pretend anything was already executed
- lack of execution evidence alone is NOT a reason to reject; use approved_execution_intent to decide whether execution may proceed
- if the worker draft is weak, vague, or risky, say revise or reject and downgrade approved_execution_intent to plan_only
- the final reply should be what the end user should read
- if mode is brief, optimize for publishable project brief quality
- if mode is patch, optimize for engineering correctness and safety
- if mode is research, optimize for evidence quality and clarity
- approved_* 字段应尽量从草案中收敛出更可信的版本，而不是重新发明
- 如果草案证据不足，approved_execution_intent 应退回 plan_only
- if approved_proposed_changes and approved_verification_steps are already concrete and low-risk, you may keep approved_execution_intent=apply_patch even when the worker's proposed_commands are informal or placeholder-like

{profile_instructions}

Detected mode:
{mode}

Engineering context:
{engineering_context}

Review profile:
{review_profile}

User task:
{prompt}

Bailian worker draft:
{json.dumps(review_payload, ensure_ascii=False, indent=2)}
"""
    with tempfile.NamedTemporaryFile(prefix="remote-agent-hybrid-codex-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                args.codex_bin,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--cd",
                args.workdir,
                "--output-last-message",
                str(output_path),
                reviewer_prompt,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
        reply = output_path.read_text(errors="ignore").strip() if output_path.exists() else ""
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Codex review failed")
        return parse_json_object(reply or completed.stdout.strip())
    finally:
        output_path.unlink(missing_ok=True)


def execute_approved_actions(
    args: argparse.Namespace,
    prompt: str,
    worker_output: dict[str, object],
    review_output: dict[str, object],
) -> dict[str, object]:
    intent = str(review_output.get("approved_execution_intent", "plan_only")).strip().lower()
    if intent == "plan_only":
        return {
            "status": "skipped",
            "intent": "plan_only",
            "summary": "审核结果要求停留在方案层，未进入自动执行。",
            "touched_files": [],
            "verification_results": [],
        }
    if intent == "tool_exec":
        return {
            "status": "skipped",
            "intent": "tool_exec",
            "summary": "tool_exec 暂未接入自动执行层，当前仍停留在受控审核阶段。",
            "touched_files": [],
            "verification_results": [],
        }
    if intent != "apply_patch":
        return {
            "status": "skipped",
            "intent": intent or "unknown",
            "summary": "未识别的 execution intent，未执行。",
            "touched_files": [],
            "verification_results": [],
        }

    execution_prompt = f"""Apply the approved patch plan in the current repository and return strict JSON only.

Return format:
{{
  "status": "executed|failed|partial",
  "summary": "...",
  "touched_files": ["...", "..."],
  "verification_results": ["...", "..."],
  "followups": ["...", "..."]
}}

Rules:
- language: Simplified Chinese
- make the approved changes directly in the worktree
- do not touch files outside the approved scope unless absolutely required for correctness; if you do, state why
- run lightweight verification where possible
- if the approved plan is insufficient to make a safe change, return failed and explain why
- touched_files must be repo-relative when possible

User task:
{prompt}

Worker mode:
{worker_output.get("mode", "general")}

Engineering context:
{worker_output.get("engineering_context", "none")}

Approved execution intent:
{intent}

Approved files to check:
{json.dumps(review_output.get("approved_files_to_check", []), ensure_ascii=False, indent=2)}

Approved proposed changes:
{json.dumps(review_output.get("approved_proposed_changes", []), ensure_ascii=False, indent=2)}

Approved verification steps:
{json.dumps(review_output.get("approved_verification_steps", []), ensure_ascii=False, indent=2)}

Review notes:
{json.dumps(review_output.get("review_notes", []), ensure_ascii=False, indent=2)}
"""

    with tempfile.NamedTemporaryFile(prefix="remote-agent-hybrid-exec-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                args.codex_bin,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--cd",
                args.workdir,
                "--output-last-message",
                str(output_path),
                execution_prompt,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
        reply = output_path.read_text(errors="ignore").strip() if output_path.exists() else ""
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Codex execution failed")
        result = parse_json_object(reply or completed.stdout.strip())
        result.setdefault("intent", intent)
        return result
    finally:
        output_path.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    prompt = Path(args.prompt_file).read_text(errors="ignore").strip()
    response_path = Path(args.response_file)
    try:
        worker_output = run_bailian_worker(args, prompt)
        codex_review = run_codex_review(args, prompt, worker_output)
        review_profile = str(worker_output.get("classification", {}).get("review_profile", "standard"))
        execution = execute_approved_actions(args, prompt, worker_output, codex_review)
        final_reply = str(codex_review.get("final_reply", "")).strip()
        if str(execution.get("status", "")).strip().lower() == "executed":
            final_reply = str(execution.get("summary", final_reply)).strip() or final_reply
        payload = {
            "id": args.command_id,
            "ok": True,
            "type": "hybrid",
            "input_mode": args.input_mode,
            "status": "completed",
            "finished_at": now_iso(),
            "host": args.host,
            "result": {
                "workdir": str(Path(args.workdir).expanduser().resolve()),
                "reply": trim_text(final_reply, args.max_output_chars),
                "worker": worker_output,
                "review": codex_review,
                "execution": execution,
                "meta": {
                    "worker": str(worker_output.get("worker_backend", "direct_bailian")),
                    "reviewer": "codex-cli",
                    "async": True,
                    "mode": worker_output.get("mode", "general"),
                    "review_profile": review_profile,
                    "engineering_context": worker_output.get("engineering_context", "none"),
                },
            },
        }
    except Exception as exc:
        payload = {
            "id": args.command_id,
            "ok": False,
            "type": "hybrid",
            "input_mode": args.input_mode,
            "status": "failed",
            "finished_at": now_iso(),
            "host": args.host,
            "error": trim_text(str(exc), args.max_output_chars),
        }
    finally:
        Path(args.prompt_file).unlink(missing_ok=True)

    response_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
