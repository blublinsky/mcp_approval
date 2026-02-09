#!/usr/bin/env python3
"""Test script to verify MCP server functionality without full dependencies."""

import asyncio

import httpx


async def test_mcp_server():
    """Test the MCP server endpoints."""
    base_url = "http://localhost:3000"

    print("Testing MCP Server")
    print("=" * 60)
    print()

    async with httpx.AsyncClient() as client:
        # Test 1: Health endpoint
        print("Test 1: Health endpoint")
        try:
            response = await client.get(f"{base_url}/health", timeout=5.0)
            data = response.json()
            print(f"✓ Health check passed: {data}")
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return False
        print()

        # Test 2: Initialize
        print("Test 2: Initialize")
        try:
            response = await client.post(
                base_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                timeout=5.0,
            )
            data = response.json()
            if "result" in data and "serverInfo" in data["result"]:
                print(
                    f"✓ Initialize successful: {data['result']['serverInfo']['name']}"
                )
            else:
                print("❌ Initialize failed: unexpected response")
                return False
        except Exception as e:
            print(f"❌ Initialize failed: {e}")
            return False
        print()

        # Test 3: List tools
        print("Test 3: List tools")
        try:
            response = await client.post(
                base_url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                timeout=5.0,
            )
            data = response.json()
            if "result" in data and "tools" in data["result"]:
                tools = data["result"]["tools"]
                print(f"✓ Found {len(tools)} tools:")

                safe_tools = []
                dangerous_tools = []

                for tool in tools:
                    desc_lower = tool["description"].lower()
                    is_dangerous = any(
                        kw in desc_lower
                        for kw in ["delete", "send", "execute", "modify"]
                    )

                    if is_dangerous:
                        dangerous_tools.append(tool["name"])
                    else:
                        safe_tools.append(tool["name"])

                print(f"\n  Safe tools ({len(safe_tools)}):")
                for name in safe_tools:
                    print(f"    - {name}")

                print(
                    f"\n  Dangerous tools ({len(dangerous_tools)}) - require approval:"
                )
                for name in dangerous_tools:
                    print(f"    ⚠️  {name}")
            else:
                print("❌ List tools failed: unexpected response")
                return False
        except Exception as e:
            print(f"❌ List tools failed: {e}")
            return False
        print()

        # Test 4: Call a safe tool
        print("Test 4: Call safe tool (list_users)")
        try:
            response = await client.post(
                base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "list_users", "arguments": {}},
                },
                timeout=5.0,
            )
            data = response.json()
            if "result" in data and "content" in data["result"]:
                content = data["result"]["content"][0]["text"]
                print("✓ Tool executed successfully")
                print(f"  Result: {content[:100]}...")
            else:
                print("❌ Tool call failed: unexpected response")
                return False
        except Exception as e:
            print(f"❌ Tool call failed: {e}")
            return False
        print()

        # Test 5: Call a dangerous tool (simulated)
        print("Test 5: Call dangerous tool (delete_file)")
        print("  Note: This would normally require approval")
        try:
            response = await client.post(
                base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "delete_file",
                        "arguments": {"path": "test.txt"},
                    },
                },
                timeout=5.0,
            )
            data = response.json()
            if "result" in data and "content" in data["result"]:
                content = data["result"]["content"][0]["text"]
                print("✓ Tool executed (server doesn't enforce approval)")
                print(f"  Result: {content}")
            else:
                print("❌ Tool call failed: unexpected response")
                return False
        except Exception as e:
            print(f"❌ Tool call failed: {e}")
            return False
        print()

    print("=" * 60)
    print("✓ All tests passed!")
    print()
    print("The MCP server is working correctly.")
    print("Approval enforcement happens in the client (approval_client.py)")
    print()

    return True


async def main():
    """Main test function."""
    print()
    print("MCP Server Test Suite")
    print("=" * 60)
    print()
    print("Make sure the MCP server is running:")
    print("  python mcp_server.py")
    print()
    input("Press Enter when ready...")
    print()

    success = await test_mcp_server()

    if success:
        print("✓ All tests passed! The server is ready to use.")
        return 0
    else:
        print("❌ Some tests failed. Check the output above.")
        return 1


if __name__ == "__main__":
    import sys

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
