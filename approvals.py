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
import logging
from abc import ABC, abstractmethod
from typing import Callable, TypeAlias, TypeVar

from pydantic import BaseModel, Field, field_validator

from cli_handler import default_cli_approval_handler

logger = logging.getLogger(__name__)

# TypeVar for generic timeout utility
T = TypeVar("T")


# ============================================================================
# Type Definitions
# ============================================================================

# JSON-serializable types for tool arguments
JsonPrimitive: TypeAlias = str | int | float | bool | None
# Using object for args to avoid recursive type complexity
ToolArgs: TypeAlias = dict[str, object]


class ToolRequest(BaseModel):
    """Type definition for a tool call request with runtime validation.

    This represents a single tool invocation with all its metadata.
    """

    name: str = Field(min_length=1, description="Tool name")
    description: str = Field(default="", description="Tool description")
    args: ToolArgs = Field(default_factory=dict, description="Tool arguments")
    client: str = Field(default=None, description="Client ID")

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        """Validate that name is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError("Tool name cannot be empty")
        return v.strip()


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

    approval_ui_handler: Callable[[ToolRequest], bool] = Field(
        default=default_cli_approval_handler,
        description="Approval UI handler function. Defaults to CLI handler.",
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

    def __init__(self, config: BaseApprovalConfig):
        """Initialize approval system.

        Args:
            config: Approval configuration
        """
        self.approval_timeout = config.approval_timeout
        self.approval_ui_handler = config.approval_ui_handler

    @abstractmethod
    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool call needs approval and get approval if needed.

        Args:
            tool_request: Tool call requiring approval check

        Returns:
            bool: True if approved, False if rejected
        """

    @staticmethod
    def contains_dangerous_words(text: str, dangerous_words: list[str]) -> bool:
        """Check if text contains any dangerous words (case-insensitive).

        Args:
            text: Text to search in (assumed lowercase)
            dangerous_words: List of words to search for (assumed lowercase)

        Returns:
            bool: True if any dangerous word is found
        """
        return any(word in text for word in dangerous_words)

    async def _request_approval(self, tool_request: ToolRequest, reason: str) -> bool:
        """Request approval from user with timeout.

        Args:
            tool_request: Tool request requiring approval
            reason: Reason for approval request (for logging)

        Returns:
            bool: True if approved, False if rejected
        """
        logger.info("Tool %s requires approval (%s)", tool_request.name, reason)
        approved = await self.call_approval_handler_with_timeout(
            self.approval_ui_handler,
            tool_request,
            self.approval_timeout,
        )
        if approved:
            logger.info("User approved: %s", tool_request.name)
        else:
            logger.info("User rejected: %s", tool_request.name)
        return approved

    @staticmethod
    async def call_approval_handler_with_timeout(
        handler: Callable[[ToolRequest], bool],
        tool_request: ToolRequest,
        timeout_seconds: int,
    ) -> bool:
        """Call approval handler with timeout.

        Args:
            handler: The approval handler function
            tool_request: Tool request requiring approval
            timeout_seconds: Timeout in seconds

        Returns:
            bool: True if approved, False if rejected (rejects on timeout)
        """
        result = await call_with_timeout(
            handler, tool_request, timeout_seconds=timeout_seconds
        )

        if result is None:
            # Timeout occurred - always reject for safety
            logger.warning(
                "Approval timed out after %d seconds for tool: %s",
                timeout_seconds,
                tool_request.name,
            )
            logger.info("Auto-rejecting %s due to timeout (safer)", tool_request.name)
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
    ):
        """Initialize tool-level approval.

        Args:
            config: Tool-level approval configuration
        """
        super().__init__(config)
        self.dangerous_verbs = [v.lower() for v in config.dangerous_verbs]

    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool needs approval based on name/description.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if approved, False if rejected
        """
        tool_name = tool_request.name.lower()
        tool_desc = tool_request.description.lower()

        # Check if tool name or description contains dangerous verbs
        is_dangerous = self.contains_dangerous_words(
            tool_name, self.dangerous_verbs
        ) or self.contains_dangerous_words(tool_desc, self.dangerous_verbs)

        if not is_dangerous:
            logger.debug("Tool %s auto-approved (safe)", tool_request.name)
            return True

        # Dangerous tool - ask for approval
        return await self._request_approval(tool_request, "dangerous tool")


# ============================================================================
# Call-Level Approval
# ============================================================================


class CallLevelApproval(ToolLevelApproval):
    """Call-level approval.

    Checks tool name, description AND runtime arguments.
    Uses declarative approval rules for argument patterns.
    """

    def __init__(self, config: CallLevelApprovalConfig):
        """Initialize call-level approval.

        Args:
            config: Call-level approval configuration
        """
        super().__init__(config)
        # Normalize approval rules to lowercase for case-insensitive matching
        self.approval_rules = {
            tool_name: {
                arg_name: [keyword.lower() for keyword in keywords]
                for arg_name, keywords in arg_rules.items()
            }
            for tool_name, arg_rules in config.approval_rules.items()
        }

    async def check_and_approve_tool(self, tool_request: ToolRequest) -> bool:
        """Check if tool needs approval based on name/description/arguments.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if approved, False if rejected
        """
        tool_name = tool_request.name.lower()
        tool_desc = tool_request.description.lower()

        # Check tool-level safety first
        is_tool_dangerous = self.contains_dangerous_words(
            tool_name, self.dangerous_verbs
        ) or self.contains_dangerous_words(tool_desc, self.dangerous_verbs)

        if is_tool_dangerous:
            # Tool is dangerous - ask for approval
            return await self._request_approval(tool_request, "dangerous tool")

        # Tool is safe, check arguments
        is_args_dangerous = self._check_arguments_dangerous(tool_request)

        if is_args_dangerous:
            # Args are dangerous - ask for approval
            return await self._request_approval(tool_request, "dangerous args")

        # Both tool and args are safe - auto-approve
        logger.debug("Tool %s auto-approved (safe)", tool_request.name)
        return True

    def _check_arguments_dangerous(self, tool_request: ToolRequest) -> bool:
        """Check if arguments match dangerous patterns.

        Args:
            tool_request: Tool call to check

        Returns:
            bool: True if arguments are dangerous
        """
        tool_name = tool_request.name
        args = tool_request.args

        # Check if tool has approval rules
        if tool_name not in self.approval_rules:
            return False

        tool_rules = self.approval_rules[tool_name]

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
# Timeout Utilities
# ============================================================================


async def call_with_timeout(
    func: Callable[..., T], *args: object, timeout_seconds: int
) -> T | None:
    """Call any async function with timeout.

    Generic timeout wrapper for any async operation (tools, LLM, approvals, etc.).

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
