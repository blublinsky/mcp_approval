#!/usr/bin/env python3
"""Enhanced MCP Mock Server with approval-worthy tools.

This server provides a mix of safe and dangerous operations to demonstrate
the human-in-the-loop approval workflow.

Safe tools (no approval needed):
- list_users: Lists all users
- get_file: Retrieves file content

Dangerous tools (require approval):
- delete_file: Deletes a file (destructive)
- send_email: Sends an email (external action)
- execute_command: Runs a system command (dangerous)
- modify_database: Modifies database records (destructive)
"""

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# Global storage
request_log: list = []


class ApprovalMCPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for approval-demo MCP server."""

    def log_message(self, fmt: str, *args: object) -> None:
        """Log requests with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {fmt % args}")

    def _handle_initialize(self, request_id: int) -> dict:
        """Handle MCP initialize request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "approval-demo-mcp-server",
                    "version": "1.0.0",
                },
            },
        }

    def _handle_tools_list(self, request_id: int) -> dict:
        """Handle MCP tools/list request - return mix of safe and dangerous tools."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    # Safe tools
                    {
                        "name": "list_users",
                        "description": "List all users in the system",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                    {
                        "name": "get_file",
                        "description": "Retrieve the content of a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file",
                                }
                            },
                            "required": ["path"],
                        },
                    },
                    {
                        "name": "search_logs",
                        "description": "Search through system logs",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Search query",
                                }
                            },
                            "required": ["query"],
                        },
                    },
                    # Dangerous tools (require approval)
                    {
                        "name": "delete_file",
                        "description": (
                            "Delete a file from the filesystem "
                            "(destructive operation)"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Path to the file to delete",
                                }
                            },
                            "required": ["path"],
                        },
                    },
                    {
                        "name": "send_email",
                        "description": (
                            "Send an email to recipients " "(external communication)"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "to": {
                                    "type": "string",
                                    "description": "Recipient email address",
                                },
                                "subject": {
                                    "type": "string",
                                    "description": "Email subject",
                                },
                                "body": {
                                    "type": "string",
                                    "description": "Email body",
                                },
                            },
                            "required": ["to", "subject", "body"],
                        },
                    },
                    {
                        "name": "execute_command",
                        "description": (
                            "Execute a system command " "(potentially dangerous)"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "Command to execute",
                                }
                            },
                            "required": ["command"],
                        },
                    },
                    {
                        "name": "modify_database",
                        "description": (
                            "Modify database records " "(destructive operation)"
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "table": {
                                    "type": "string",
                                    "description": "Table name",
                                },
                                "query": {
                                    "type": "string",
                                    "description": "SQL query to execute",
                                },
                            },
                            "required": ["table", "query"],
                        },
                    },
                ]
            },
        }

    def _handle_tools_call(self, request_id: int, request_data: dict) -> dict:
        """Handle MCP tools/call request - execute a tool."""
        params = request_data.get("params", {})
        tool_name = params.get("name", "unknown")
        arguments = params.get("arguments", {})

        # Simulate tool execution
        result_text = self._execute_tool(tool_name, arguments)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": False,
            },
        }

    def _handle_unknown_method(self, request_id: int) -> dict:
        """Handle unknown MCP method."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"status": "ok"},
        }

    def do_POST(self) -> None:
        """Handle POST requests (MCP protocol endpoints)."""
        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            request_data = json.loads(body.decode("utf-8"))
            request_id = request_data.get("id", 1)
            method = request_data.get("method", "unknown")
        except (json.JSONDecodeError, UnicodeDecodeError):
            request_data = {}
            request_id = 1
            method = "unknown"

        # Log the request
        request_log.append(
            {
                "timestamp": datetime.now().isoformat(),
                "method": method,
                "path": self.path,
            }
        )
        if len(request_log) > 50:
            request_log.pop(0)

        # Handle MCP protocol methods
        match method:
            case "initialize":
                response = self._handle_initialize(request_id)
            case "tools/list":
                response = self._handle_tools_list(request_id)
            case "tools/call":
                response = self._handle_tools_call(request_id, request_data)
            case _:
                response = self._handle_unknown_method(request_id)

        # Send response
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Simulate tool execution and return mock results."""
        match tool_name:
            case "list_users":
                return json.dumps(
                    [
                        {"id": 1, "name": "Alice", "email": "alice@example.com"},
                        {"id": 2, "name": "Bob", "email": "bob@example.com"},
                        {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
                    ]
                )

            case "get_file":
                path = arguments.get("path", "unknown")
                content = (
                    f"Content of file '{path}':\n\n"
                    "This is mock file content.\nLine 2\nLine 3"
                )
                return content

            case "search_logs":
                query = arguments.get("query", "")
                return json.dumps(
                    [
                        {
                            "timestamp": "2026-02-02T10:30:00",
                            "level": "INFO",
                            "message": f"Log entry matching '{query}'",
                        },
                        {
                            "timestamp": "2026-02-02T10:31:00",
                            "level": "WARN",
                            "message": f"Another log with '{query}'",
                        },
                    ]
                )

            case "delete_file":
                path = arguments.get("path", "unknown")
                return f"✓ File '{path}' has been deleted successfully"

            case "send_email":
                to = arguments.get("to", "unknown")
                subject = arguments.get("subject", "")
                return f"✓ Email sent to '{to}' with subject '{subject}'"

            case "execute_command":
                command = arguments.get("command", "unknown")
                return f"✓ Command executed: {command}\nOutput: Mock command output"

            case "modify_database":
                table = arguments.get("table", "unknown")
                query = arguments.get("query", "")
                return f"✓ Database modified: {query} on table '{table}'"

            case _:
                return (
                    f"Tool '{tool_name}' executed with arguments: "
                    f"{json.dumps(arguments)}"
                )

    def do_GET(self) -> None:
        """Handle GET requests (debug endpoints)."""
        match self.path:
            case "/debug/requests":
                self._send_json_response(request_log)
            case "/health":
                self._send_json_response({"status": "healthy", "tools": 7})
            case "/":
                self._send_help_page()
            case _:
                self.send_response(404)
                self.end_headers()

    def _send_json_response(self, data: dict | list) -> None:
        """Send a JSON response."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _send_help_page(self) -> None:
        """Send HTML help page."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        help_html = """<!DOCTYPE html>
        <html>
        <head><title>Approval Demo MCP Server</title></head>
        <body>
            <h1>MCP Approval Demo Server</h1>
            <h2>Available Tools:</h2>
            <h3>Safe Tools (No Approval):</h3>
            <ul>
                <li><b>list_users</b> - List all users</li>
                <li><b>get_file</b> - Get file content</li>
                <li><b>search_logs</b> - Search logs</li>
            </ul>
            <h3>Dangerous Tools (Require Approval):</h3>
            <ul>
                <li><b>delete_file</b> - Delete a file</li>
                <li><b>send_email</b> - Send an email</li>
                <li><b>execute_command</b> - Execute system command</li>
                <li><b>modify_database</b> - Modify database</li>
            </ul>
            <h2>Debug Endpoints:</h2>
            <ul>
                <li>
                    <a href="/debug/requests">/debug/requests</a>
                    - View request log
                </li>
                <li><a href="/health">/health</a> - Health check</li>
            </ul>
        </body>
        </html>
        """
        self.wfile.write(help_html.encode())


def main() -> None:
    """Start the approval demo MCP server."""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000

    server = HTTPServer(("", port), ApprovalMCPHandler)

    print("=" * 70)
    print("MCP Approval Demo Server")
    print("=" * 70)
    print(f"Server: http://localhost:{port}")
    print("=" * 70)
    print("Tools available:")
    print("  Safe: list_users, get_file, search_logs")
    print("  Dangerous: delete_file, send_email, execute_command, modify_database")
    print("=" * 70)
    print("Debug endpoints:")
    print(f"  • http://localhost:{port}/debug/requests")
    print(f"  • http://localhost:{port}/health")
    print("=" * 70)
    print("Press Ctrl+C to stop")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == "__main__":
    main()
