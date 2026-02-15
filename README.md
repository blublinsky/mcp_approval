# MCP Approval - Tool Call Approval System

A production-ready, pluggable approval system for AI tool calls with Model Context Protocol (MCP) integration.

## Overview

This project provides two types of approval mechanisms:

1. **Tool-Level Approval** - Approves/rejects based on tool name and description
2. **Call-Level Approval** - Extends tool-level by checking runtime arguments (e.g., `get` is safe unless `all_namespaces=True`)

Both integrate seamlessly with LangChain agents and MCP servers.

## Quick Start

### 1. Install Dependencies

```bash
make install
```

### 2. Set API Key

```bash
export OPENAI_API_KEY='sk-...'
```

### 3. Run the Demos

```bash
# Start the mock MCP server (in one terminal)
make server

# Run the LangGraph demo (in another terminal)
make demo

# Or run the OLS-style streaming demo
make demo-ols
```

### 4. Cleanup (Optional)

```bash
# Clean temporary files and caches (__pycache__, *.pyc, .pytest_cache, *.egg-info)
make clean

# To remove the virtual environment, run:
# rm -rf .venv
```

## Core Components

### `approvals.py` - Core Approval Logic

Standalone, reusable approval classes:

**Classes:**
- `BaseApprovalConfig` - Base configuration with common fields
- `ToolLevelApprovalConfig` - Config for tool-level approval
- `CallLevelApprovalConfig` - Config for call-level approval (extends ToolLevelApprovalConfig)
- `BaseApproval` - Abstract base class for approval handlers
- `ToolLevelApproval` - Approves based on tool name/description containing dangerous verbs
- `CallLevelApproval` - Extends ToolLevelApproval with argument pattern matching
- `ToolRequest` - TypedDict for tool call structure
- `default_cli_approval_handler` - Default CLI approval interface

**Example:**
```python
from approvals import ToolLevelApproval, ToolLevelApprovalConfig

config = ToolLevelApprovalConfig(dangerous_verbs=["delete", "remove"])
approval = ToolLevelApproval(config=config)

tool_request = {"name": "kubectl_delete", "description": "...", "args": {...}}
approved = await approval.check_and_approve_tool(tool_request)
```

### `approval_client.py` - LangChain/MCP Integration

LangChain agent integration with MCP servers.

**Functions:**
- `discover_mcp_tools()` - Connects to MCP server and retrieves tools
- `create_approval_agent()` - Creates LangChain agent with approval middleware
- `invoke_with_approval()` - Handles agent execution with approval loop

**Example:**
```python
from approval_client import create_approval_agent, invoke_with_approval

agent, approval = await create_approval_agent(
    mcp_url="http://localhost:3000",
    api_key=os.getenv("OPENAI_API_KEY")
)

result = await invoke_with_approval(
    agent, approval, "Delete test.txt", {"configurable": {"thread_id": "1"}}
)
```

### `demo_approval_client.py` - LangGraph Demos

Comprehensive demos using LangGraph agent with three scenarios:
1. Tool-level approval
2. Call-level approval with argument patterns
3. Custom domain-specific rules

### `ols_approval_client.py` - OLS-Style Streaming Client

Alternative client implementation using LangChain's native tool calling with streaming support:

**Classes:**
- `StreamedChunk` - Represents chunks of streamed response (text, tool_call, tool_result, end)
- `OLSApprovalClient` - Streaming client with integrated approval support

**Features:**
- Native LLM streaming with `llm.astream()`
- Tool execution with approval checks
- Separate timeouts for LLM (60s) and tool execution (30s)
- Clean streaming API returning text, tool calls, and tool results

**Example:**
```python
from ols_approval_client import OLSApprovalClient
from approvals import ToolLevelApprovalConfig, default_cli_approval_handler

config = ToolLevelApprovalConfig(
    dangerous_verbs=["delete", "remove", "send"],
    approval_timeout=10,
    approval_ui_handler=default_cli_approval_handler,
)

client = OLSApprovalClient(
    mcp_url="http://localhost:3000",
    model="gpt-4o",
    api_key=api_key,
    approval_config=config,
)

result = await client.invoke("Delete test.txt")
print(result["response"])
```

### `demo_ols_approval_client.py` - OLS Streaming Demos

Demonstrates the OLS-style client with two scenarios:
1. Without approvals - tools execute automatically
2. With tool-level approval - dangerous operations require confirmation

### `mcp_server.py` - Mock MCP Server

Test server with safe and dangerous tools for testing approval workflows.

## Key Features

- ✅ **Pluggable UI**: Custom approval handlers (CLI, web, Slack, etc.)
- ✅ **Type Safety**: Pydantic configs with validation
- ✅ **Two Approval Modes**: Tool-level and call-level
- ✅ **Auto-Approval**: Safe tools bypass approval
- ✅ **Performance**: Short-circuit evaluation, lowercase caching
- ✅ **KISS**: Simple, focused, maintainable
- ✅ **MCP Integration**: Works with any MCP server
- ✅ **LangChain Compatible**: Uses HumanInTheLoopMiddleware

## Additional reading

- [Creating an Advanced AI Agent from Scratch with Python — Part 1](https://pub.towardsai.net/creating-an-advanced-ai-agent-from-scratch-with-python-in-2025-part-1-ce74a23f6514)
- [Creating an Advanced AI Agent from Scratch with Python — Part 2](https://pub.towardsai.net/creating-an-advanced-ai-agent-from-scratch-with-python-in-2026-part-2-0f41c8d80bff)
