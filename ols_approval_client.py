#!/usr/bin/env python3
"""OLS-style MCP client with tool calling and approval support.

This demonstrates an alternative approach using LangChain's native tool calling
and streaming, similar to the OLS implementation, with integrated approval system.
"""

import asyncio
import logging
from typing import Any, AsyncGenerator, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.ai import AIMessageChunk
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from approvals import (
    BaseApproval,
    CallLevelApproval,
    CallLevelApprovalConfig,
    ToolLevelApproval,
    ToolLevelApprovalConfig,
    ToolRequest,
    call_with_timeout,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# Timeout for individual tool execution (seconds)
TOOL_EXECUTION_TIMEOUT = 30

# Timeout for LLM response generation (seconds)
LLM_TIMEOUT = 60


class StreamedChunk:
    """Represents a chunk of streamed response."""

    def __init__(
        self, chunk_type: str, text: str = "", data: dict[str, Any] | None = None
    ):
        self.type = chunk_type
        self.text = text
        self.data = data or {}


def tool_calls_from_tool_calls_chunks(
    tool_calls_chunks: list[AIMessageChunk],
) -> list[dict[str, Any]]:
    """Extract complete tool calls from a series of tool call chunks.

    Args:
        tool_calls_chunks: List of AIMessageChunk objects containing partial tool calls

    Returns:
        List of complete tool call dictionaries
    """
    # LangChain magic to concatenate messages and create final tool calls
    response = AIMessageChunk(content="")
    for chunk in tool_calls_chunks:
        response += chunk  # type: ignore [assignment]
    return response.tool_calls


async def get_mcp_tools(mcp_url: str) -> list:
    """Get tools from MCP server.

    Args:
        mcp_url: URL of the MCP server

    Returns:
        List of LangChain tools
    """
    client = MultiServerMCPClient(
        {
            "demo_server": {
                "transport": "http",
                "url": mcp_url,
            }
        }
    )
    tools = await client.get_tools()
    logger.info("Retrieved %d tools via MCP adapter", len(tools))
    return tools


async def execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    all_tools: list,
    approval: Optional[BaseApproval] = None,
) -> list[BaseMessage]:
    """Execute tool calls with optional approval and return tool messages.

    Args:
        tool_calls: List of tool call dictionaries from LLM
        all_tools: List of available LangChain tools
        approval: Optional approval instance for dangerous operations

    Returns:
        List of ToolMessage objects with results
    """

    tool_messages = []
    tools_by_name = {tool.name: tool for tool in all_tools}

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id")

        logger.info("Executing tool: %s with args: %s", tool_name, tool_args)

        # Check approval if approval system is enabled
        if approval:
            tool = tools_by_name.get(tool_name)
            tool_request: ToolRequest = {
                "name": tool_name,
                "description": tool.description if tool else "",
                "args": tool_args,
            }

            try:
                approved = await approval.check_and_approve_tool(tool_request)
                if not approved:
                    result = f"Tool execution denied by approval system: {tool_name}"
                    status = "error"
                    logger.warning("Tool %s was rejected by approval", tool_name)
                    tool_messages.append(
                        ToolMessage(
                            content=str(result), tool_call_id=tool_id, status=status
                        )
                    )
                    continue
            except Exception as e:  # pylint: disable=broad-exception-caught
                result = f"Approval check failed: {str(e)}"
                status = "error"
                logger.error("Approval check error: %s", e, exc_info=True)
                tool_messages.append(
                    ToolMessage(
                        content=str(result), tool_call_id=tool_id, status=status
                    )
                )
                continue

        # Execute the tool if approved (or no approval system)
        try:
            tool = tools_by_name.get(tool_name)
            if not tool:
                result = f"Error: Tool '{tool_name}' not found"
                status = "error"
            else:
                # Execute the tool with timeout
                result = await call_with_timeout(
                    tool.ainvoke, tool_args, timeout_seconds=TOOL_EXECUTION_TIMEOUT
                )
                if result is None:
                    result = (
                        f"Tool execution timed out after "
                        f"{TOOL_EXECUTION_TIMEOUT} seconds"
                    )
                    status = "error"
                else:
                    status = "success"
        except Exception as e:  # pylint: disable=broad-exception-caught
            result = f"Error executing tool: {str(e)}"
            status = "error"
            logger.error("Tool execution failed: %s", e, exc_info=True)

        tool_messages.append(
            ToolMessage(content=str(result), tool_call_id=tool_id, status=status)
        )

    return tool_messages


class OLSApprovalClient:
    """OLS-style MCP client with tool calling and approval support."""

    def __init__(
        self,
        mcp_url: str = "http://localhost:3000",
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        approval_config: Optional[
            ToolLevelApprovalConfig | CallLevelApprovalConfig
        ] = None,
    ):
        """Initialize the OLS-style client with optional approval.

        Args:
            mcp_url: URL of the MCP server
            model: OpenAI model to use
            api_key: OpenAI API key
            approval_config: Optional approval configuration (Tool-level or Call-level)
        """
        self.mcp_url = mcp_url
        self.model = model
        self.api_key = api_key

        # Create LLM
        self.llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=0,
        )

        # Create approval instance if config provided
        if approval_config:
            if isinstance(approval_config, CallLevelApprovalConfig):
                self.approval: Optional[BaseApproval] = CallLevelApproval(
                    config=approval_config
                )
            else:
                self.approval = ToolLevelApproval(config=approval_config)
        else:
            self.approval = None

    async def _invoke_llm(
        self,
        messages: list[BaseMessage],
        tools: list,
        is_final_round: bool,
    ) -> AsyncGenerator[AIMessageChunk, None]:
        """Invoke the LLM with optional tools and timeout.

        Args:
            messages: List of messages to send to LLM
            tools: List of available tools
            is_final_round: Whether this is the final round (no tools)

        Yields:
            AIMessageChunk objects from the LLM response stream
        """
        # Bind tools only if not final round and tools are available
        llm = self.llm if is_final_round or not tools else self.llm.bind_tools(tools)

        try:
            # Stream with timeout
            async with asyncio.timeout(LLM_TIMEOUT):
                async for chunk in llm.astream(messages):
                    yield chunk  # type: ignore [misc]
        except asyncio.TimeoutError:
            logger.error("LLM response timed out after %d seconds", LLM_TIMEOUT)
            # Yield error chunk
            yield AIMessageChunk(
                content=f"Error: LLM response timed out after {LLM_TIMEOUT} seconds"
            )

    async def iterate_with_tools(
        self,
        messages: list[BaseMessage],
        max_rounds: int,
        all_tools: list,
    ) -> AsyncGenerator[StreamedChunk, None]:
        """Iterate through multiple rounds of LLM invocation with tool calling.

        Args:
            messages: Initial messages
            max_rounds: Maximum number of tool calling rounds
            all_tools: List of MCP tools

        Yields:
            StreamedChunk objects representing parts of the response
        """
        for i in range(1, max_rounds + 1):
            is_final_round = i == max_rounds
            logger.info("Tool calling round %d (final: %s)", i, is_final_round)

            tool_call_chunks = []

            # Invoke LLM and process response chunks
            async for chunk in self._invoke_llm(messages, all_tools, is_final_round):
                # Check if LLM has finished generating
                finish_reason = chunk.response_metadata.get("finish_reason")
                if finish_reason == "stop":  # type: ignore [attr-defined]
                    return

                # Collect tool chunk or yield text
                if getattr(chunk, "tool_call_chunks", None):
                    tool_call_chunks.append(chunk)
                else:
                    # Stream text chunks directly
                    yield StreamedChunk(chunk_type="text", text=chunk.content)

            # Exit if this was the final round
            if is_final_round:
                break

            # Tool calling part
            if tool_call_chunks:
                # Extract complete tool calls
                tool_calls = tool_calls_from_tool_calls_chunks(tool_call_chunks)
                ai_tool_call_message = AIMessage(
                    content="", type="ai", tool_calls=tool_calls
                )
                messages.append(ai_tool_call_message)

                for tool_call in tool_calls:
                    logger.info(
                        "Tool call: %s with args: %s",
                        tool_call.get("name"),
                        tool_call.get("args"),
                    )
                    yield StreamedChunk(chunk_type="tool_call", data=tool_call)

                # Execute tools with approval
                tool_messages = await execute_tool_calls(
                    tool_calls, all_tools, self.approval
                )
                messages.extend(tool_messages)

                for tool_message in tool_messages:
                    logger.info(
                        "Tool result for %s: status=%s",
                        tool_message.tool_call_id,
                        tool_message.status,
                    )
                    yield StreamedChunk(
                        chunk_type="tool_result",
                        data={
                            "id": tool_message.tool_call_id,
                            "status": tool_message.status,
                            "content": tool_message.content,
                            "round": i,
                        },
                    )

    async def generate_response(
        self,
        query: str,
        history: Optional[list[BaseMessage]] = None,
        max_rounds: int = 3,
    ) -> AsyncGenerator[StreamedChunk, None]:
        """Generate a response for the given query.

        Args:
            query: The query to be answered
            history: Optional conversation history
            max_rounds: Maximum number of tool calling rounds

        Yields:
            StreamedChunk objects representing parts of the response
        """
        # Get MCP tools
        all_tools = await get_mcp_tools(self.mcp_url)

        # Prepare messages
        messages: list[BaseMessage] = []
        if history:
            messages.extend(history)

        # Add system prompt
        system_message = AIMessage(
            content=(
                "You are a helpful assistant with access to tools. "
                "When the user asks you to perform an action, "
                "you MUST call the appropriate tool to accomplish it. "
                "Do NOT just explain what you would do - "
                "ALWAYS call the tool directly."
            )
        )
        messages.insert(0, system_message)

        # Add user query
        messages.append(HumanMessage(content=query))

        # Iterate with tools
        async for chunk in self.iterate_with_tools(messages, max_rounds, all_tools):
            yield chunk

        yield StreamedChunk(chunk_type="end")

    async def invoke(
        self,
        query: str,
        history: Optional[list[BaseMessage]] = None,
        max_rounds: int = 3,
    ) -> dict[str, Any]:
        """Invoke the client and collect complete response.

        Args:
            query: The query to be answered
            history: Optional conversation history
            max_rounds: Maximum number of tool calling rounds

        Returns:
            Dictionary with response, tool_calls, and tool_results
        """
        text_chunks = []
        tool_calls = []
        tool_results = []

        async for chunk in self.generate_response(query, history, max_rounds):
            if chunk.type == "text":
                text_chunks.append(chunk.text)
            elif chunk.type == "tool_call":
                tool_calls.append(chunk.data)
            elif chunk.type == "tool_result":
                tool_results.append(chunk.data)
            elif chunk.type == "end":
                break

        return {
            "response": "".join(text_chunks),
            "tool_calls": tool_calls,
            "tool_results": tool_results,
        }
