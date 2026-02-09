"""
OLS-Style Client Demo with Approval Support

This demonstrates the OLS-style client with:
1. No approvals - tools execute automatically
2. Tool-level approval - requires approval for dangerous tools
"""

import asyncio
import logging
import os

from approvals import (
    ToolLevelApprovalConfig,
    default_cli_approval_handler,
)
from ols_approval_client import OLSApprovalClient


async def main():
    """Demo the OLS-style client with and without approvals."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        return

    print("=" * 70)
    print("OLS-Style MCP Client Demo with Approval Support")
    print("=" * 70 + "\n")

    # DEMO 1: Without approvals
    print("\n" + "=" * 70)
    print("DEMO 1: WITHOUT APPROVALS")
    print("=" * 70 + "\n")

    client_no_approval = OLSApprovalClient(
        mcp_url="http://localhost:3000",
        model="gpt-4o",
        api_key=api_key,
    )

    queries = [
        "List all users in the system",
    ]

    for i, query in enumerate(queries, 1):
        print(f"Query {i}: {query}\n")
        result = await client_no_approval.invoke(query)
        print(f"Response: {result['response']}\n")

    # DEMO 2: With Tool-Level Approval
    print("\n" + "=" * 70)
    print("DEMO 2: WITH TOOL-LEVEL APPROVAL")
    print("=" * 70)
    print("Dangerous verbs (delete, remove, etc.) require approval")
    print("=" * 70 + "\n")

    approval_config = ToolLevelApprovalConfig(
        dangerous_verbs=["delete", "remove", "send"],
        approval_timeout=10,  # 10 seconds for demo
        approval_ui_handler=default_cli_approval_handler,
    )

    client_with_approval = OLSApprovalClient(
        mcp_url="http://localhost:3000",
        model="gpt-4o",
        api_key=api_key,
        approval_config=approval_config,
    )

    queries_approval = [
        "Delete the file test.txt",  # Requires approval
        # Requires approval
        "Send an email to team@example.com with subject 'Test' and body 'Hello'",
    ]

    for i, query in enumerate(queries_approval, 1):
        print(f"\n--- Query {i}: {query} ---\n")
        print("=" * 70)
        print(f"User Query: {query}")
        print("=" * 70 + "\n")

        result = await client_with_approval.invoke(query)

        print("\n" + "=" * 70)
        print("FINAL RESULT")
        print("=" * 70)
        print(result["response"])
        print("=" * 70)

        if result["tool_calls"]:
            print(f"\nTool calls made: {len(result['tool_calls'])}")
            for tc in result["tool_calls"]:
                print(f"  - {tc.get('name')}: {tc.get('args')}")

        print("\n" + "-" * 70)

    print("\n" + "=" * 70)
    print("All demos complete!")
    print("=" * 70)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s"
    )
    asyncio.run(main())
