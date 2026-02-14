#!/usr/bin/env python3
"""MCP approval workflow using the approvals' module.

This demonstrates integration with LangChain agents:
1. Agent discovers tools from MCP server
2. Tools are checked against approval rules
3. Dangerous tools trigger approval via pluggable UI
4. Agent resumes with user's decision
"""

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

# Import from centralized approvals module
from approvals import (
    BaseApproval,
    BaseApprovalConfig,
    CallLevelApproval,
    CallLevelApprovalConfig,
    ToolLevelApproval,
    ToolLevelApprovalConfig,
    ToolRequest,
)
from cli_handler import default_cli_approval_handler

# ============================================================================
# MCP Tool Discovery
# ============================================================================


async def discover_mcp_tools(mcp_url: str):
    """Discover tools from MCP server using langchain_mcp_adapters."""
    client = MultiServerMCPClient(
        {
            "demo_server": {
                "transport": "http",
                "url": mcp_url,
            }
        }
    )

    tools = await client.get_tools()
    print(f"✓ Retrieved {len(tools)} tools via MCP adapter")
    return tools


# ============================================================================
# Agent Creation with Approval
# ============================================================================


async def create_approval_agent(
    mcp_url: str = "http://localhost:3000",
    model: str = "gpt-4o",
    config: BaseApprovalConfig | None = None,
    api_key: str | None = None,
):
    """Create an agent with approval workflow.

    Works with both ToolLevelApproval and CallLevelApproval.

    Args:
        mcp_url: URL of the MCP server
        model: LLM model to use
        config: BaseApprovalConfig (ToolLevelApprovalConfig or CallLevelApprovalConfig)
        api_key: OpenAI API key (required)

    Returns:
        Tuple of (agent, approval_instance) for use with invoke_with_approval

    Examples:
        # Tool-level approval (default)
        agent, approval = await create_approval_agent(api_key=key)

        # Tool-level with custom config
        config = ToolLevelApprovalConfig(
            dangerous_verbs=["delete", "drop", "destroy"],
            approval_ui_handler=default_cli_approval_handler
        )
        agent, approval = await create_approval_agent(api_key=key, config=config)

        # Call-level approval (argument-based)
        config = CallLevelApprovalConfig(
            dangerous_verbs=["delete", "get"],
            approval_rules={
                "get": ["all_namespaces"],
                "delete": ["*"],
            },
            approval_ui_handler=default_cli_approval_handler
        )
        agent, approval = await create_approval_agent(api_key=key, config=config)
    """
    # Use default config if none provided
    if config is None:
        config = ToolLevelApprovalConfig(
            approval_ui_handler=default_cli_approval_handler
        )

    # Create approval instance based on config type
    if isinstance(config, CallLevelApprovalConfig):
        approval = CallLevelApproval(config=config)
    else:
        approval = ToolLevelApproval(config=config)

    # Discover tools from MCP server
    tools = await discover_mcp_tools(mcp_url)

    # Build interrupt map: interrupt on ALL tools
    # The approval logic will decide whether to prompt or auto-approve
    interrupt_on = {}
    for tool in tools:
        interrupt_on[tool.name] = {
            "allowed_decisions": ["approve", "reject"],
            "description": f"⚠️  {tool.name} requires approval: {tool.description}",
        }

    approval_type = (
        "Call-level" if isinstance(approval, CallLevelApproval) else "Tool-level"
    )
    print(f"✓ Discovered {len(tools)} tools from MCP server")
    print(f"✓ Using {approval_type} approval")
    print(
        "✓ Interrupting on all tool calls "
        "(approval logic will auto-approve safe tools)"
    )

    # Create LLM
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        temperature=0,
    )

    # Create agent with approval middleware
    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=(
            "You are a helpful assistant with access to tools. "
            "IMPORTANT: When the user asks you to perform an action, "
            "you MUST call the appropriate tool to accomplish it. "
            "Do NOT just explain what you would do or ask for confirmation - "
            "ALWAYS call the tool directly. "
            "The approval system will handle any necessary confirmations. "
            "Your job is to call tools, not to ask permission."
        ),
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on=interrupt_on,
                description_prefix="⚠️  Tool execution requires approval",
            )
        ],
        checkpointer=MemorySaver(),  # Required for interrupts
    )

    return agent, approval


# ============================================================================
# Invocation with Approval Loop
# ============================================================================


async def invoke_with_approval(
    agent: CompiledStateGraph,
    approval: BaseApproval,
    query: str,
    config: RunnableConfig,
) -> dict[str, object]:
    """Invoke agent and handle approval loop.

    Works with both ToolLevelApproval and CallLevelApproval.

    Args:
        agent: The LangChain agent
        approval: BaseApproval instance (ToolLevelApproval or CallLevelApproval)
        query: User query string
        config: LangGraph config dict with thread_id

    Returns:
        Final result dict from agent execution

    Example:
        agent, approval = await create_approval_agent(api_key=key)
        result = await invoke_with_approval(
            agent,
            approval,
            "Delete file.txt",
            {"configurable": {"thread_id": "demo_1"}}
        )
    """
    print(f"\n{'='*70}")
    print(f"User Query: {query}")
    print(f"{'='*70}\n")

    # Initial invocation
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": query}]}, config=config
    )

    # Handle interrupts (approval requests)
    while "__interrupt__" in result:
        # Extract approval requests from interrupt
        interrupts = result["__interrupt__"]
        for interrupt_data in interrupts:
            interrupt_value = (
                interrupt_data.value
                if hasattr(interrupt_data, "value")
                else interrupt_data
            )

            if (
                isinstance(interrupt_value, dict)
                and "action_requests" in interrupt_value
            ):
                action_requests = interrupt_value["action_requests"]

                # Process each action request through approval
                decisions = []
                for action_request in action_requests:
                    # Convert to ToolRequest format
                    tool_request: ToolRequest = {
                        "name": action_request["name"],
                        "args": action_request.get("args", {}),
                        "description": action_request.get(
                            "description", f"Tool: {action_request['name']}"
                        ),
                    }

                    # Check and get approval
                    approved = await approval.check_and_approve_tool(tool_request)

                    # Convert bool to LangChain decision format
                    if approved:
                        decisions.append({"type": "approve"})
                    else:
                        decisions.append(
                            {
                                "type": "reject",
                                "message": f"User rejected {tool_request['name']}",
                            }
                        )

                # Resume execution with decisions
                result = await agent.ainvoke(
                    Command(resume={"decisions": decisions}), config=config
                )

    # Print final result
    if result and "messages" in result and result["messages"]:
        final_message = result["messages"][-1]
        print(f"\n{'='*70}")
        print("FINAL RESULT")
        print(f"{'='*70}")
        print(final_message.content)
        print(f"{'='*70}\n")

    return result
