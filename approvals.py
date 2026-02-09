"""Approval system for MCP tool calls.

This module provides a standalone approval system that can be integrated
into any agent framework. It supports:

1. Tool-Level Approval: Based on tool name and description
2. Call-Level Approval: Based on tool arguments at runtime

Key Features:
- Declarative configuration via Pydantic models
- Pluggable UI handlers (CLI, GUI, web, etc.)
- Stateless approval logic
- Full type safety with TypedDict and Pydantic
- Timeout support for approval prompts and tool execution
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

logger = logging.getLogger(__name__)


# ============================================================================
# Type Definitions
# ============================================================================


class ToolRequest(TypedDict):
    """Type definition for a tool call request.

    This represents a single tool invocation with all its metadata.
    """

    name: str
    description: str
    args: dict[str, Any]
    metadata: NotRequired[dict[str, Any]]


# ============================================================================
# Configuration Models
# ============================================================================


class BaseApprovalConfig(BaseModel):
    """Base configuration for approval systems."""

    model_config = {"arbitrary_types_allowed": True}

    approval_timeout: int = Field(
        default=30,
        description="Timeout in seconds for user to respond to approval prompt",
    )

    on_approval_timeout_auto_approve: bool = Field(
        default=False,
        description=(
            "Auto-approve (True, risky) or auto-reject (False, safer) "
            "when approval times out"
        ),
    )

    approval_ui_handler: Optional[Callable[[ToolRequest], bool]] = Field(
        default=None,
        description=(
            "Custom approval UI handler function. " "If None, uses default CLI handler."
        ),
    )


class ToolLevelApprovalConfig(BaseApprovalConfig):
    """Configuration for tool-level approval.

    Approval based on tool name and description only.
    Checks for dangerous verbs like 'delete', 'remove', etc.
    """

    dangerous_verbs: list[str] = Field(
        default_factory=lambda: [
            "delete",
            "remove",
            "drop",
            "truncate",
            "destroy",
            "kill",
            "terminate",
            "shutdown",
            "reboot",
            "restart",
            "modify",
            "update",
            "execute",
            "run",
            "eval",
        ],
        description="List of verbs that trigger approval (case-insensitive)",
    )


class CallLevelApprovalConfig(ToolLevelApprovalConfig):
    """Configuration for call-level approval.

    Approval based on tool name, description AND runtime arguments.
    Supports declarative approval rules for specific argument patterns.
    """

    approval_rules: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description=(
            "Declarative approval rules: {tool_name: {arg_name: [keywords]}}. "
            "Example: {'delete_file': {'path': ['/etc', '/sys', 'production']}}"
        ),
    )


# ============================================================================
# Base Approval Class
# ============================================================================


class BaseApproval(ABC):
    """Abstract base class for approval systems."""

    def __init__(
        self,
        config: BaseApprovalConfig,
        approval_ui_handler: Optional[Callable[[ToolRequest], bool]] = None,
    ):
        """Initialize approval system.

        Args:
            config: Approval configuration
            approval_ui_handler: Function to display approval prompt and get user input.
                                 If not provided, uses config.approval_ui_handler,
                                 otherwise falls back to default_cli_approval_handler.
        """
        self.config = config
        # Priority: parameter > config.approval_ui_handler > default
        if approval_ui_handler is not None:
            self.approval_ui_handler = approval_ui_handler
        elif config.approval_ui_handler is not None:
            self.approval_ui_handler = config.approval_ui_handler
        else:
            self.approval_ui_handler = default_cli_approval_handler

    @abstractmethod
    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool call needs approval and get approval if needed.

        Args:
            tool_request: Tool call requiring approval check

        Returns:
            bool: True if approved, False if rejected
        """

    def contains_dangerous_words(self, text: str, dangerous_words: list[str]) -> bool:
        """Check if text contains any dangerous words (case-insensitive).

        Args:
            text: Text to search in (assumed lowercase)
            dangerous_words: List of words to search for (assumed lowercase)

        Returns:
            bool: True if any dangerous word is found
        """
        return any(word in text for word in dangerous_words)

    async def call_approval_handler_with_timeout(
        self,
        handler: Callable[[ToolRequest], bool],
        tool_request: ToolRequest,
        timeout_seconds: int,
        auto_approve_on_timeout: bool = False,
    ) -> bool:
        """Call approval handler with timeout.

        Args:
            handler: The approval handler function
            tool_request: Tool request requiring approval
            timeout_seconds: Timeout in seconds
            auto_approve_on_timeout: If True, approve on timeout; if False, reject

        Returns:
            bool: True if approved, False if rejected
        """
        result = await call_with_timeout(
            handler, tool_request, timeout_seconds=timeout_seconds
        )

        if result is None:
            # Timeout occurred
            logger.warning(
                "Approval timed out after %d seconds for tool: %s",
                timeout_seconds,
                tool_request["name"],
            )
            if auto_approve_on_timeout:
                logger.warning(
                    "Auto-approving %s due to timeout (risky!)", tool_request["name"]
                )
                return True
            logger.info(
                "Auto-rejecting %s due to timeout (safer)", tool_request["name"]
            )
            return False

        return result


# ============================================================================
# Tool-Level Approval
# ============================================================================


class ToolLevelApproval(BaseApproval):
    """Tool-level approval.

    Checks tool name and description for dangerous verbs.
    Auto-approves safe tools, asks for approval on dangerous ones.
    """

    def __init__(
        self,
        config: ToolLevelApprovalConfig,
        approval_ui_handler: Optional[Callable[[ToolRequest], bool]] = None,
    ):
        """Initialize tool-level approval.

        Args:
            config: Tool-level approval configuration
            approval_ui_handler: Function to display approval prompt
        """
        super().__init__(config, approval_ui_handler)
        self.config: ToolLevelApprovalConfig = config

    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool needs approval based on name/description.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if approved, False if rejected
        """
        tool_name = tool_request["name"].lower()
        tool_desc = tool_request["description"].lower()
        dangerous_verbs = [v.lower() for v in self.config.dangerous_verbs]

        # Check if tool name or description contains dangerous verbs
        is_dangerous = self.contains_dangerous_words(
            tool_name, dangerous_verbs
        ) or self.contains_dangerous_words(tool_desc, dangerous_verbs)

        if not is_dangerous:
            logger.debug("Tool %s auto-approved (safe)", tool_request["name"])
            return True

        # Dangerous tool - ask for approval with timeout
        logger.info("Tool %s requires approval (dangerous)", tool_request["name"])
        approved = await self.call_approval_handler_with_timeout(
            self.approval_ui_handler,
            tool_request,
            self.config.approval_timeout,
            self.config.on_approval_timeout_auto_approve,
        )

        if approved:
            logger.info("User approved: %s", tool_request["name"])
        else:
            logger.info("User rejected: %s", tool_request["name"])

        return approved


# ============================================================================
# Call-Level Approval
# ============================================================================


class CallLevelApproval(BaseApproval):
    """Call-level approval.

    Checks tool name, description AND runtime arguments.
    Uses declarative approval rules for argument patterns.
    """

    def __init__(
        self,
        config: CallLevelApprovalConfig,
        approval_ui_handler: Optional[Callable[[ToolRequest], bool]] = None,
    ):
        """Initialize call-level approval.

        Args:
            config: Call-level approval configuration
            approval_ui_handler: Function to display approval prompt
        """
        super().__init__(config, approval_ui_handler)
        self.config: CallLevelApprovalConfig = config

    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool needs approval based on name/description/arguments.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if approved, False if rejected
        """
        tool_name = tool_request["name"].lower()
        tool_desc = tool_request["description"].lower()
        dangerous_verbs = [v.lower() for v in self.config.dangerous_verbs]

        # Check tool-level safety first
        is_tool_dangerous = self.contains_dangerous_words(
            tool_name, dangerous_verbs
        ) or self.contains_dangerous_words(tool_desc, dangerous_verbs)

        # Check call-level safety (arguments)
        is_args_dangerous = self._check_arguments_dangerous(tool_request)

        if not is_tool_dangerous and not is_args_dangerous:
            logger.debug("Tool %s auto-approved (safe)", tool_request["name"])
            return True

        # Dangerous tool/args - ask for approval with timeout
        logger.info(
            "Tool %s with args requires approval (dangerous)", tool_request["name"]
        )
        approved = await self.call_approval_handler_with_timeout(
            self.approval_ui_handler,
            tool_request,
            self.config.approval_timeout,
            self.config.on_approval_timeout_auto_approve,
        )

        if approved:
            logger.info("User approved: %s with args", tool_request["name"])
        else:
            logger.info("User rejected: %s with args", tool_request["name"])

        return approved

    def _check_arguments_dangerous(self, tool_request: ToolRequest) -> bool:
        """Check if arguments match dangerous patterns.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if arguments are dangerous
        """
        tool_name = tool_request["name"]
        args = tool_request["args"]

        # Check if tool has approval rules
        if tool_name not in self.config.approval_rules:
            return False

        tool_rules = self.config.approval_rules[tool_name]

        # Check each argument against its rules
        for arg_name, dangerous_keywords in tool_rules.items():
            if arg_name not in args:
                continue

            arg_value = str(args[arg_name]).lower()

            # Check if argument contains any dangerous keyword
            for keyword in dangerous_keywords:
                if keyword.lower() in arg_value:
                    logger.debug(
                        "Dangerous argument detected: %s=%s contains '%s'",
                        arg_name,
                        arg_value,
                        keyword,
                    )
                    return True

        return False


# ============================================================================
# Default UI Handler
# ============================================================================


async def default_cli_approval_handler(tool_request: ToolRequest) -> bool:
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
        tool_request: Tool call requiring approval

    Returns:
        bool: True if approved, False if rejected
    """
    print("\n" + "=" * 70)
    print("🚨 APPROVAL REQUIRED")
    print("=" * 70)

    print(f"Tool: {tool_request['name']}")
    print(f"Description: {tool_request['description']}")
    print("Arguments:")
    print(json.dumps(tool_request["args"], indent=2))
    print()

    loop = asyncio.get_running_loop()

    try:
        while True:
            # Run input() in executor to avoid blocking event loop
            choice = await loop.run_in_executor(None, lambda: input("Approve? (y/n): "))
            choice = choice.lower().strip()

            if choice == "y":
                print("✅ Approved\n")
                print("=" * 70)
                return True
            elif choice == "n":
                print("❌ Rejected\n")
                print("=" * 70)
                return False
            elif choice == "":
                # Empty input - don't print error, just ask again
                continue
            else:
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


# ============================================================================
# Timeout Utilities
# ============================================================================


async def call_with_timeout(
    func: Callable, *args: Any, timeout_seconds: int
) -> Any | None:
    """Call any async function with timeout.

    Generic timeout wrapper for any async operation (tools, LLM, approvals, etc).

    Args:
        func: Async callable to execute
        *args: Positional arguments for func
        timeout_seconds: Timeout in seconds

    Returns:
        Result from func on success, None on timeout

    Example:
        result = await call_with_timeout(tool.ainvoke, tool_args, timeout_seconds=30)
        if result is None:
            print("Tool execution timed out")
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            return await func(*args)
    except asyncio.TimeoutError:
        logger.warning(
            "Operation timed out after %d seconds: %s",
            timeout_seconds,
            func.__name__ if hasattr(func, "__name__") else str(func),
        )
        return None
