"""CLI approval handler for terminal-based approval prompts.

This module provides a default command-line interface for approval requests.
For production use, consider implementing a web-based or GUI handler instead.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


async def default_cli_approval_handler(tool_request) -> bool:
    """Default CLI approval handler with timeout support.

    Runs input() in an executor thread so the async event loop isn't blocked.

    ⚠️  TIMEOUT LIMITATION: The timeout only fires if you don't press any keys.
    Each time you press Enter (even without typing), input() returns immediately,
    which resets the wait. The timeout is measured from the LAST keypress, not
    from when the prompt first appeared.

    To trigger timeout: Wait 10 seconds without touching the keyboard at all.

    ⚠️  ZOMBIE THREADS: When timeout occurs, the thread running input() remains
    blocked until you press Enter. This is unavoidable with Python's input().
    Threads are cleaned up when the program exits.

    For production: Use a web-based approval UI instead of CLI input().

    Args:
        tool_request: ToolRequest with name, description, args fields

    Returns:
        bool: True if approved, False if rejected
    """
    print("\n" + "=" * 70)
    print("🚨 APPROVAL REQUIRED")
    print("=" * 70)

    print(f"Tool: {tool_request.name}")
    print(f"Description: {tool_request.description}")
    print("Arguments:")
    print(json.dumps(tool_request.args, indent=2))
    print()

    loop = asyncio.get_running_loop()

    try:
        while True:
            # Run input() in executor to avoid blocking event loop
            choice = await loop.run_in_executor(None, lambda: input("Approve? (y/n): "))
            choice = choice.lower().strip()

            match choice:
                case "y":
                    print("✅ Approved\n")
                    print("=" * 70)
                    return True
                case "n":
                    print("❌ Rejected\n")
                    print("=" * 70)
                    return False
                case "":
                    # Empty input - don't print error, just ask again
                    continue
                case _:
                    print("Invalid input. Enter y or n\n")

    except asyncio.CancelledError:
        # Timeout cancelled this coroutine
        print("\n❌ Timed out (treated as rejection)\n")
        print("=" * 70)
        return False
    except (KeyboardInterrupt, EOFError):
        # User cancelled (Ctrl-C or Ctrl-D) - treat as rejection
        print("\n❌ Cancelled (treated as rejection)\n")
        print("=" * 70)
        return False
