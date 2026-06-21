import os
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

SYSTEM = f"You are a coding agent at {WORKDIR}. Use bash to solve tasks. Act, don't explain."

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
]


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

# 映射，工具分发
TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}

# ═══════════════════════════════════════════════════════════
#  NEW in s03: 三道安全闸门
# ═══════════════════════════════════════════════════════════

# 1.硬拒绝表
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot",  "mkfs", "dd if=", "> /dev/sda",]

def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Blocked: '{pattern}' is on the deny list"
    return None

# 2.规则匹配
PERMISSION_RULES = [
    {"tools": ["write_file", "edit_file"],
     "check": lambda args: not (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR),
     "message": "Writing outside workspace"},
    {"tools": ["bash"],
     "check": lambda args: any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
     "message": "Potentially destructive command"},
]   # message：触发规则时的提示信息，check：一个 lambda 函数，接收参数字典 args，返回 True 表示触发了这条规则（有风险）

def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]      # 返回该规则的提示信息（表示有风险）
    return None

# 3.人工审批 → 当 闸门2 检测到风险时，暂停程序，等待用户决定
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"   Tool: {tool_name}({args})")
    choice = input("   Allow? [y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"

# 三道闸门串联
def check_permission(block) -> bool:
    # Gate 1 只对 bash 命令生效
    if block.name == "bash":
        reason = check_deny_list(block.input.get("command", ""))
        if reason:
            print(f"\n\033[31m⛔ {reason}\033[0m")
            return False
    # Gate 2 规则检查，对所有工具生效    
    reason = check_rules(block.name, block.input)
    # 进入 Gate 3 询问用户
    if reason:
        decision = ask_user(block.name, block.input, reason)
        if decision == "deny":
            return False
    return True

# ── The core pattern: a while loop that calls tools until the model stops ──
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # Append assistant turn 追加回复response.content至历史消息列表
        messages.append({"role": "assistant", "content": response.content})

        # If the model didn't call a tool, we're done
        # 停止原因包含"end_turn自然结束"、"max_tokens"、"tool_use"、"stop_sequence遇到停止词"
        if response.stop_reason != "tool_use":
            return

        # Execute each tool call, collect results Execute each tool call, collect results
        results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m$ {block.name}\033[0m")
                # 新增：告知大模型请求被拒绝
                if not check_permission(block):
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": "Permission denied."})
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                #output = run_bash(block.input["command"])
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
                print(output[:200])
                results.append({
                    "type": "tool_result",      # 工具执行结果
                    "tool_use_id": block.id,
                    "content": output,      # 工具执行的实际返回
                })

        # Feed tool results back, loop continues 将工具结果反馈，循环继续
        messages.append({"role": "user", "content": results})


# ── Entry point ──────────────────────────────────────────
if __name__ == "__main__":
    print("s02: Tool Use")
    print("输入问题，回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the model's final text response 打印模型的最终文本响应
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()