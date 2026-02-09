#!/usr/bin/env python3
"""Demo script showing both ToolLevelApproval and CallLevelApproval.

This demonstrates:
1. Tool-level approval - approves/rejects based on tool name/description
2. Call-level approval - approves/rejects based on tool arguments
"""

import asyncio
import os

from langchain_core.runnables import RunnableConfig

from approval_client import create_approval_agent, invoke_with_approval
from approvals import (
    CallLevelApprovalConfig,
    ToolLevelApprovalConfig,
    default_cli_approval_handler,
)


async def demo_tool_level_approval(api_key: str):
    """Demonstrate tool-level approval."""
    print("\n" + "=" * 70)
    print("DEMO 1: TOOL-LEVEL APPROVAL")
    print("=" * 70)
    print("Approves/rejects based on tool name and description")
    print("Any tool with dangerous verbs (delete, remove, etc.) needs approval")
    print("=" * 70 + "\n")

    # Configure tool-level approval
    config = ToolLevelApprovalConfig(
        dangerous_verbs=["delete", "remove", "destroy"],
        approval_timeout=10,  # 10 seconds for easier testing
        approval_ui_handler=default_cli_approval_handler,
    )

    # Create agent
    agent, approval = await create_approval_agent(
        mcp_url="http://localhost:3000",
        model="gpt-4o",
        config=config,
        api_key=api_key,
    )

    # Test queries
    queries = [
        "List all users",  # Safe
        "Delete the file test.txt",  # Dangerous - needs approval
    ]

    for i, query in enumerate(queries):
        print(f"\n--- Query {i+1}: {query} ---")
        config_dict: RunnableConfig = {"configurable": {"thread_id": f"tool_level_{i}"}}
        await invoke_with_approval(agent, approval, query, config_dict)
        print("\n" + "-" * 70)


async def demo_call_level_approval(api_key: str):
    """Demonstrate call-level (argument-based) approval."""
    print("\n" + "=" * 70)
    print("DEMO 2: CALL-LEVEL APPROVAL")
    print("=" * 70)
    print("Approves/rejects based on tool name + arguments")
    print("Example: 'delete' always needs approval")
    print("=" * 70 + "\n")

    # Configure call-level approval
    config = CallLevelApprovalConfig(
        dangerous_verbs=["delete", "remove"],
        approval_rules={
            # Format: {tool_name: {arg_name: [keywords]}}
            "delete_file": {
                "path": ["/etc", "/sys", "/tmp"],  # Dangerous paths
            },
        },
        approval_timeout=10,  # 10 seconds for easier testing
        approval_ui_handler=default_cli_approval_handler,
    )

    # Create agent
    agent, approval = await create_approval_agent(
        mcp_url="http://localhost:3000",
        model="gpt-4o",
        config=config,
        api_key=api_key,
    )

    # Test queries
    queries = [
        "Search logs for errors in the last hour",  # Safe - auto-approved
        # Safe normally, dangerous patterns would trigger approval
        "Get the file /etc/config.yaml",
        "Delete the file /tmp/cache.txt",  # Dangerous - delete verb
    ]

    for i, query in enumerate(queries):
        print(f"\n--- Query {i+1}: {query} ---")
        config_dict: RunnableConfig = {"configurable": {"thread_id": f"call_level_{i}"}}
        await invoke_with_approval(agent, approval, query, config_dict)
        print("\n" + "-" * 70)


async def demo_custom_config(api_key: str):
    """Demonstrate custom configuration."""
    print("\n" + "=" * 70)
    print("DEMO 3: CUSTOM CONFIGURATION")
    print("=" * 70)
    print("Custom dangerous verbs and approval rules")
    print("=" * 70 + "\n")

    # Custom config with domain-specific rules
    config = CallLevelApprovalConfig(
        dangerous_verbs=["send", "email", "notify", "execute"],
        approval_rules={
            # Format: {tool_name: {arg_name: [keywords]}}
            "send_email": {
                "to": ["*"],  # Always need approval for any recipient
            },
            "execute_command": {
                "command": [
                    "production",
                    "live",
                ],  # Only production execution needs approval
            },
        },
        approval_timeout=10,  # 10 seconds for easier testing
        approval_ui_handler=default_cli_approval_handler,
    )

    # Create agent
    agent, approval = await create_approval_agent(
        mcp_url="http://localhost:3000",
        model="gpt-4o",
        config=config,
        api_key=api_key,
    )

    # Test queries
    queries = [
        # Dangerous - send verb always needs approval
        (
            "Send an email to team@example.com with subject 'Update' "
            "and body 'Status update'"
        ),
        # Safe - dev environment is allowed
        "Use the execute_command tool to run 'ls -la' command",
        # Dangerous - production pattern needs approval
        "Use the execute_command tool to run 'systemctl status app' in production",
    ]

    for i, query in enumerate(queries):
        print(f"\n--- Query {i+1}: {query} ---")
        config_dict: RunnableConfig = {"configurable": {"thread_id": f"custom_{i}"}}
        await invoke_with_approval(agent, approval, query, config_dict)
        print("\n" + "-" * 70)


async def main():
    """Run all demos."""
    print("=" * 70)
    print("MCP Approval Client Demo")
    print("=" * 70)
    print()
    print("This demo shows both approval types:")
    print("1. Tool-Level: Approve based on tool name/description")
    print("2. Call-Level: Approve based on tool arguments")
    print("3. Custom: Domain-specific approval rules")
    print()

    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        print("   Set it with: export OPENAI_API_KEY='sk-...'")
        return

    # Run demos
    await demo_tool_level_approval(api_key)
    await demo_call_level_approval(api_key)
    await demo_custom_config(api_key)

    print("\n" + "=" * 70)
    print("All demos complete!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
