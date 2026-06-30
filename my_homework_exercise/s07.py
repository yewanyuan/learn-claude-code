import os, ast, json, yaml
import subprocess
from pathlib import Path

try:
    import readline
    # macOS 的 libedit 在处理中文输入时有退格问题，这四行修复它
    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
WORKDIR = Path.cwd()    # 获取当前工作目录
SKILLS_DIR = WORKDIR / "skills"

# s07: 元数据解析
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """将文件拆分为元数据(meta，包含 name 和 description)和正文(body)"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()

# Build skill registry at startup (used for safe lookup in load_skill)
SKILL_REGISTRY: dict[str, dict] = {}

def _scan_skills():
    """Scan skills/ dir, populate SKILL_REGISTRY with name/description/content."""
    if not SKILLS_DIR.exists():
        return
    # 读取每个子目录下的 SKILL.md，解析出元数据和完整内容
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "SKILL.md"
        if manifest.exists():
            raw = manifest.read_text()
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", d.name)
            desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
            # 缓存到全局字典
            SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}

_scan_skills()  # 初始化技能注册表

def list_skills() -> str:
    """List all skills (name + one-line description)."""
    if not SKILL_REGISTRY:
        return "(no skills found)"
    # 把技能的名字和一句话描述（目录）放进 System Prompt
    return "\n".join(f"- **{s['name']}**: {s['description']}" for s in SKILL_REGISTRY.values())

# s07: SYSTEM includes skill catalog (cheap — just names + descriptions)
def build_system() -> str:
    """Build SYSTEM prompt with skill catalog injected at startup."""
    catalog = list_skills()
    return (
        f"You are a coding agent at {WORKDIR}. "
        f"Skills available:\n{catalog}\n"
        "Use load_skill to get full details when needed."
    )

SYSTEM = build_system()

# s07: subagent gets its own system prompt — no skill loading, no task
SUB_SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Complete the task you were given, then return a concise summary. "
    "Do not delegate further."
)

# ── Tool execution ────────────────────────────────────────
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        # 调用了 Python 标准库 subprocess 的 run 方法来执行命令
        r = subprocess.run(command, 
                           shell=True,      # 允许通过系统的默认 Shell
                           cwd=os.getcwd(),     # 设置执行命令时的工作目录为当前脚本所在的目录
                           capture_output=True, # 捕获命令的标准输出和标准错误
                           text=True,   # 将输出的结果自动解码为字符串
                           timeout=120,
                           encoding="utf-8")
        # 如果命令执行成功，返回标准输出，否则返回标准错误
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    # 捕获系统级异常
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

# 安全路径检查
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()  # 将传入的相对路径 p 与预设的工作目录 WORKDIR 拼接,并使用 resolve() 方法将其解析为绝对路径
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

# 读文件
def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()    # 读取文件内容，并按行分割
        if limit and limit < len(lines):
            # 只保留前 limit 行，并额外加一行提示告诉 AI 后面还有多少行没显示
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)     # 把行列表重新拼成字符串返回
    except Exception as e:
        return f"Error: {e}"

# 写文件
def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        # 如果目标文件所在的父目录不存在，自动创建（parents=True 递归创建，exist_ok=True 如果存在不报错）
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")   # 内容写入
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

# 编辑文件
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text(encoding="utf-8")    # 读取当前文件的所有内容
        if old_text not in text:    # 检查想要替换的旧文本在文件中是否存在
            return f"Error: text not found in {path}"
        # 旧文本替换为新文本。关键点：replace(..., 1) 中的 1 表示只替换第一处匹配
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

# 文件搜索
def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        # 在 WORKDIR 目录下搜索匹配 pattern 的文件路径
        for match in g.glob(pattern, root_dir=WORKDIR):
            # 双重检查，确定检索到的文件没有逃出工作区
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"

# 数据清洗与校验
def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            # 如果传入的是字符串，先尝试用 json.loads 解析
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                # 如果失败，降级尝试用 ast.literal_eval
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        # 确保最终解析出来的 todos 是一个列表
        return None, "Error: todos must be a list"
    for i, t in enumerate(todos):
        # 确保每一项是字典
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        # 确保每一项包含 'content' 和 'status'
        if "content" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        # 确保 status 只能是允许的三种状态
        if t["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None

# todo_write 工具，接收一个带状态的列表，保存在当前进程内存中，同时在终端显示进度
def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    # 调用清洗函数，如果报错直接把错误字符串返回给大模型
    todos, error = _normalize_todos(todos)
    if error:
        return error
    # 清洗成功后，更新全局任务列表
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    # 返回给大模型 确认信息
    return f"Updated {len(CURRENT_TODOS)} tasks"

# 提取纯文本
def extract_text(content) -> str:
    """Extract text from message content blocks."""
    if not isinstance(content, list):
        return str(content)
    return "\n".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")

#  NEW in s06: Subagent — fresh messages[], summary only. NO "task" tool
SUB_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
]

SUB_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}

# 子代理
def spawn_subagent(description: str) -> str:
    """Spawn a subagent with fresh messages[], return summary only."""
    # 子 Agent 的工具SUB_TOOLS：基础工具，但没有 task（禁止递归）
    print(f"\n\033[35m[Subagent spawned]\033[0m")
    # 上下文隔离，子代理启动时，主代理只传给它一句 description（任务描述）
    messages = [{"role": "user", "content": description}]  # fresh context

    for _ in range(30):  # safety limit
        response = client.messages.create(
            model=MODEL, system=SUB_SYSTEM,
            messages=messages, tools=SUB_TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # Issue 1: subagent also runs hooks (permissions apply)
                blocked = trigger_hooks("PreToolUse", block)
                if blocked:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(blocked)})
                    continue
                handler = SUB_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
                trigger_hooks("PostToolUse", block, output)
                # 日志会被压缩，且加上 [sub] 前缀
                print(f"  \033[90m[sub] {block.name}: {str(output)[:100]}\033[0m")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        messages.append({"role": "user", "content": results})

    # Issue 5: fallback if safety limit hit during tool_use
    result = extract_text(messages[-1]["content"])
    # 如果子代理跑满了循环还没结束，代码会从后往前遍历历史记录，努力寻找最后一段 assistant 的文字回复
    if not result:
        # last message is tool_result, look backwards for assistant text
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                result = extract_text(msg["content"])
                if result:
                    break
        # 无结果则返回提示
        if not result:
            result = "Subagent stopped after 30 turns without final answer."
    print(f"\033[35m[Subagent done]\033[0m")
    return result  # only summary, entire message history discarded

# ═══════════════════════════════════════════════════════════
#  NEW in s07: load_skill — 安全的延迟加载
# ═══════════════════════════════════════════════════════════

def load_skill(name: str) -> str:
    """Load full skill content. Lookup via registry — no path traversal."""
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]

# ── Tool definition: 工具定义 ────────────────────────────
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            },
        },
    {
        "name": "read_file", 
        "description": "Read file contents.",
        # 定义了输入参数的结构
        "input_schema": {
            "type": "object",   # 输入参数是一个 JSON 对象
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, 
            "required": ["path"]    # 列出哪些参数是必填
            }
        },
    {
        "name": "write_file", 
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object", 
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, 
            "required": ["path", "content"]
            }
        },
    {
        "name": "edit_file", 
        "description": "Replace exact text in a file once.",
        "input_schema": {
            "type": "object", 
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, 
            "required": ["path", "old_text", "new_text"]
            }
        },
    {
        "name": "glob", 
        "description": "Find files matching a glob pattern.",
        "input_schema": {
            "type": "object", 
            "properties": {"pattern": {"type": "string"}}, 
            "required": ["pattern"]
            }
        },
    # s05: new tool
    {
        "name": "todo_write", 
        "description": "Create and manage a task list for your current coding session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }
    },
    {
        "name": "task", 
        "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
        "input_schema": {
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"]
        }
    },
    # s07: skill tool (catalog is already in SYSTEM prompt, this loads full content)
    {
        "name": "load_skill", 
        "description": "Load the full content of a skill by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        }
    },
]

# 映射，工具分发
TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,"todo_write": run_todo_write,
    "task": spawn_subagent, "load_skill": load_skill,
}
# # 挂载到主代理
# TOOLS.append({
#     "name": "task",
#     "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
#     "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]},
# })
# # 把 spawn_subagent 包装成一个名叫 task 的普通工具，注册给主代理
# TOOL_HANDLERS["task"] = spawn_subagent

# ═══════════════════════════════════════════════════════════
#  NEW in s04: Hook System
# ═══════════════════════════════════════════════════════════

# hook 注册表，全局字典 4个事件
HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}
'''
UserPromptSubmit：用户提交问题时触发。
PreToolUse：工具执行之前触发（可用于权限检查、日志记录等）。
PostToolUse：工具执行之后触发（可用于输出检查、结果处理等）。
Stop：Agent 循环即将结束（模型不再调用工具）时触发。
'''

# 注册函数。将一个回调函数 callback 追加到指定事件的列表中。同一个事件可以注册多个回调，它们会按注册顺序依次执行
def register_hook(event: str, callback):
    HOOKS[event].append(callback)

# 触发函数。在 agent_loop 的关键位置调用此函数来执行所有注册的hook
def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:  # teaching shortcut: block this tool call
            return result
    return None

# 硬拒绝表
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot",  "mkfs", "dd if=", "> /dev/sda",]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

def permission_hook(block):
    """PreToolUse: s03 check_permission() logic moved here."""
    # Gate 1 — 硬拒绝名单，只对 bash 工具生效
    if block.name == "bash":
        for pattern in DENY_LIST:
            if pattern in block.input.get("command", ""):
                print(f"\n\033[31m⛔ Blocked: '{pattern}'\033[0m")
                return "Permission denied by deny list"
        # Gate 2+3 — 危险命令检测 + 人工确认
        for kw in DESTRUCTIVE:
            if kw in block.input.get("command", ""):
                print(f"\n\033[33m⚠  Potentially destructive command\033[0m")
                print(f"   Tool: {block.name}({block.input})")
                choice = input("   Allow? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
    # 对文件写入/编辑工具的路径安全检查
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m⚠  Writing outside workspace\033[0m")
            print(f"   Tool: {block.name}({block.input})")
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
    return None

# 日志记录
def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60] # 取出参数值，最多取前 2 个，最多 60 个字符
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")    # \033[90m：ANSI 灰色代码
    return None     # 不拦截，只是旁路记录

# 大输出警告
def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] ⚠ Large output from {block.name}: {len(str(output))} chars\033[0m")
    return None

# UserPromptSubmit hook: 用户提交问题时触发的hook
def context_inject_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")  # 灰色打印当前工作目录
    '''
    潜在扩展：虽然当前只是打印，但可以扩展它，比如在 return 时返回一段额外的上下文文本，
    被注入到发给大模型的消息中（比如告诉大模型当前工作目录是什么、有哪些文件等）
    '''
    return None

# Stop hook: Agent 循环结束时 会话统计
def summary_hook(messages: list):
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    '''
    for m in messages: 遍历每一条消息
    m.get("content") if isinstance(m.get("content"), list) else []: 获取消息内容，如果内容是列表则直接使用，否则为空列表
    for b in……: 遍历每一条消息的列表内容
    if isinstance(b, dict) and b.get("type") == "tool_result": 判断内容是否为字典且类型为 tool_result，是则加1
    '''
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")  # 工具调用次数
    return None

# 注册 hook
register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)    # permission_hook（先注册，先执行）
register_hook("PreToolUse", log_hook)   # log_hook（后注册，后执行）
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)

# ── s04 + nag reminder counter ──

rounds_since_todo = 0

def agent_loop(messages: list):
    global rounds_since_todo
    while True:
        # 模型连续 3 轮没调 todo_write 时，自动注入一条提醒
        if rounds_since_todo >= 3 and messages:
            messages.append({
                "role": "user",
                "content": "<reminder>Update your todos.</reminder>",
            })
            rounds_since_todo = 0

        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # Append assistant turn 追加回复response.content至历史消息列表
        messages.append({"role": "assistant", "content": response.content})

        # If the model didn't call a tool, we're done
        # 停止原因包含"end_turn自然结束"、"max_tokens"、"tool_use"、"stop_sequence遇到停止词"
        if response.stop_reason != "tool_use":
            # 如果 Stop 钩子返回了非 None 的值,意味着有人（或规则）不同意结束
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        
        rounds_since_todo += 1
        # Execute each tool call, collect results Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                # 如果被拦截，将 Hook 返回的具体原因 str(blocked) 塞进 tool_result 反馈给模型
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                # 然后跳过当前工具的执行
                continue

            handler = TOOL_HANDLERS.get(block.name)
            #output = run_bash(block.input["command"])
            output = handler(**block.input) if handler else f"Unknown: {block.name}"
            trigger_hooks("PostToolUse", block, output)     # 检查输出是否过长
            #print(output[:200])
            results.append({
                "type": "tool_result",      # 工具执行结果
                "tool_use_id": block.id,
                "content": output,      # 工具执行的实际返回
            })

        # Feed tool results back, loop continues 将工具结果反馈，循环继续
        messages.append({"role": "user", "content": results})


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s07: Skill Loading")
    print("输入问题，回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response 打印模型的最终文本响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()