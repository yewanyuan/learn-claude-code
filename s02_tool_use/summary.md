# s02_tool_use Summary

## Overview

s02 is the second module in the learn-claude-code series. It extends the single-tool Agent from s01 (which only had `bash`) to support **5 tools** via a dispatch pattern.

The core lesson: **"Add a tool, add one line"** — the main loop stays unchanged; only a new entry in `TOOL_HANDLERS` is needed.

## Tools Available (5)

| Tool | Description |
|------|-------------|
| `bash` | Run a shell command |
| `read_file` | Read file contents (with optional `limit`) |
| `write_file` | Write content to a file |
| `edit_file` | Replace text in a file once |
| `glob` | Find files by pattern |

## Key Concepts

- **TOOL_HANDLERS**: A dictionary mapping tool names → handler functions. Adding a tool = adding one mapping.
- **Tool Definition**: JSON schema describing the tool to the model.
- **Multiple Tool Calls**: The model can return multiple `tool_use` blocks at once. The educational version executes them sequentially in original order.
- **Loop Invariant**: The `while True` loop from s01 is completely unchanged.

## Architecture

The Agent loop remains the same as s01 (LLM call, stop_reason check, message appending). The only change is in the tool execution line: hardcoded `run_bash()` replaced with `TOOL_HANDLERS[block.name]()` lookup dispatch.

## Changes from s01

| Component | Before (s01) | After (s02) |
|-----------|-------------|-------------|
| Number of tools | 1 (bash) | 5 (+read, write, edit, glob) |
| Tool execution | Hardcoded `run_bash()` | TOOL_HANDLERS dispatch |
| Path safety | None | `safe_path` validation (file tools only) |
| Loop | `while True` + `stop_reason` | Identical to s01 |

## requirements.txt

**Not found** — this project does not contain a `requirements.txt` file.

## Suggested Prompts (from README)

1. Read a file and explain the project
2. Create a file, then read it back
3. Find all Python files in a directory
4. Read both README and requirements.txt, then create a summary

## Next Step

s03 introduces **Permissions** — a gate before tool execution to check safety and request user approval.
