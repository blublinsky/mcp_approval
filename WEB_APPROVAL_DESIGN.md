# Web-Based Approval System Design

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [High-Level Description](#high-level-description)
3. [Sequence Diagram](#sequence-diagram)
4. [Implementation Details](#implementation-details)
5. [Complete Code](#complete-code)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────┐
│  Main Application (React/TypeScript Frontend)           │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  <iframe src="/api/approvals/pending" />           │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────┬──────────────────────────────┘
                           │ (HTTP)
                           ▼
┌──────────────────────────────────────────────────────────┐
│  lightspeed-service (FastAPI Backend)                    │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Existing REST Endpoints                           │ │
│  │  - POST /v1/query                                  │ │
│  │  - POST /v1/streaming_query                        │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  NEW: Approval REST Endpoints                      │ │
│  │  - GET  /api/approvals/pending  (HTML or JSON)     │ │
│  │  - POST /api/approvals/{id}/decide (submit)        │ │
│  └─────────────────┬──────────────────────────────────┘ │
│                    │                                     │
│  ┌─────────────────▼──────────────────────────────────┐ │
│  │  web_approval_handler.py                          │ │
│  │  - pending_approvals: Dict (shared state)         │ │
│  │  - web_approval_handler(tool_request) -> bool     │ │
│  └─────────────────▲──────────────────────────────────┘ │
│                    │                                     │
│  ┌─────────────────┴──────────────────────────────────┐ │
│  │  ols_approval_client.py                           │ │
│  │  - Makes tool calls                                │ │
│  │  - Calls web_approval_handler() when needed        │ │
│  └────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **iframe Isolation**: Main app embeds approval UI in iframe
   - Minimal impact on main frontend (1 line of code)
   - Backend controls entire UI/UX
   - Easy to update without frontend deploy

2. **Shared In-Memory State**: `pending_approvals` dictionary
   - Simple, no external dependencies
   - Works for single-instance deployments
   - Can be replaced with OLS database for multi-instance

3. **AsyncIO Futures for Blocking**: Handler blocks until approval
   - Clean async/await pattern
   - No polling needed in backend
   - Efficient resource usage

4. **Server-Rendered HTML**: Backend serves complete UI
   - No build step needed
   - All logic in one place
   - Easy to customize per deployment

5. **Content Negotiation**: Single GET endpoint returns HTML or JSON
   - Browser/iframe requests get HTML (Accept: text/html)
   - JavaScript fetch gets JSON (Accept: application/json)

---

## High-Level Description

### Problem Statement
When an MCP server needs to execute a dangerous tool (e.g., delete_file, send_email), it must obtain human approval before proceeding.

### Solution
A web-based approval system that:
1. Blocks MCP server execution when approval needed
2. Displays pending approvals in a user-friendly table
3. Allows users to approve/reject via web UI
4. Resumes MCP server execution after decision

### User Flow

**Background**: Frontend continuously polls `GET /api/approvals/pending` (independent of query flow)

1. **User asks a question**
   - Frontend sends query to OLS (blocking request)
   - OLS invokes LLM, LLM decides to call a tool

2. **MCP server needs approval**
   - Server calls `web_approval_handler(tool_request)`
   - Handler creates Future and stores in `pending_approvals`
   - Handler blocks, waiting for user decision

3. **User views approvals**
   - Self-polling iframe detects pending approvals
   - Table renders with pending approvals
   - User clicks row to open approval modal

4. **User makes decision**
   - Reviews tool details and arguments
   - Clicks "Approve" or "Reject"
   - Frontend POSTs decision to backend

5. **MCP server resumes**
   - Backend resolves Future with user's decision
   - Handler unblocks and returns to server
   - Server continues or stops based on decision
   - On timeout (no response within `approval_timeout`), defaults to rejection

---

## Sequence Diagram

```
Background: Frontend iframe polls GET /api/approvals/pending continuously

═══════════════════════════════════════════════════════════════════════════

1. USER QUERY TRIGGERS TOOL CALL

  User ──► Frontend UI ──► OLS ──► LLM
              POST /v1/query      "Generate response"
                                       │
                                       ▼
                              LLM returns: tool call delete_file
                              (if multiple tool calls, all processed in parallel via asyncio.gather)
                                       │
                                       ▼
                                  OLS ──► MCP Server
                                     "Execute tool via MCP"

═══════════════════════════════════════════════════════════════════════════

2. MCP SERVER NEEDS APPROVAL

  MCP Server ──► web_approval_handler(tool_request)
                        │
                        ├── request_id = uuid4()
                        ├── future = Future()
                        ├── Store {id, tool_request, future} in pending_approvals
                        └── await future (BLOCKS)
                                │
                    ┌───────────┘
                    │ OLS execution paused...
                    │ waiting for human decision
                    ▼

═══════════════════════════════════════════════════════════════════════════

  ── Meanwhile, self-polling iframe detects new pending approval ──

  Approval UI (iframe) ──► GET /api/approvals/pending (every 2s)
                                    │
                                    ▼
                           Response: data.length > 0
                                    │
                                    ▼
                           Table renders with pending approvals

═══════════════════════════════════════════════════════════════════════════

3. APPROVER REVIEWS & DECIDES

  Approver ──► Clicks row in table
                    │
                    ▼
              Modal shows tool details + arguments
                    │
                    ▼
  Approver ──► Clicks "Approve"
                    │
                    ▼
  Approval UI ──► POST /api/approvals/{id}/decide {approved: true}

═══════════════════════════════════════════════════════════════════════════

4. EXECUTION RESUMES

  REST Endpoint ──► pending_approvals[id]['future'].set_result(True)
                        │
                        ▼
                    Future resolves
                        │
                        ▼
  web_approval_handler returns True ──► MCP Server
                                            │
                    ┌───────────────────────┘
                    │ OLS execution resumes
                    ▼
              MCP Server executes tool
                    │
                    ▼
              MCP ──► OLS ──► LLM ──► OLS ──► Frontend ──► User
                  result    continue   final     response
                            with result response

═══════════════════════════════════════════════════════════════════════════

5. APPROVAL UI REFRESHES

  POST response: {status: "ok"}
                    │
                    ▼
  Approval UI ──► GET /api/approvals/pending (reload table)
                    │
                    ▼
              Table updated (empty if no more pending)
```

---

## Implementation Details

### 1. Shared State Management

**Location**: `web_approval_handler.py`

**Data Structure** (Multi-User Support):
```python
# Key: user_id, Value: list of pending approvals for that user
pending_approvals: Dict[str, List[Dict]] = {
    "user-alice": [
        {
            "request_id": "abc-123",
            "tool_request": ToolRequest(name="delete_file", ...),
            "future": asyncio.Future(),
            "created_at": datetime.now()
        }
    ],
    "user-bob": [
        {
            "request_id": "def-456",
            "tool_request": ToolRequest(name="send_email", ...),
            "future": asyncio.Future(),
            "created_at": datetime.now()
        }
    ]
}
```

**Note**: In-memory state only works for single-instance deployments. When OLS runs behind a load balancer, the approval request and the polling GET may hit different instances. In production, replace with the existing OLS database (already used for conversation history), which all instances can access.

**Lifecycle**:
- **Created**: When `web_approval_handler()` is called, new approval added to user's list
- **Read**: GET endpoint filters by authenticated user_id
- **Resolved**: POST endpoint sets Future result
- **Cleanup**: After Future resolves, approval is removed from user's list (via `finally` block in handler — see [Complete Code](#complete-code))

**Key Points**:
- User ID comes from OLS auth system (`retrieve_user_id(auth)`)
- Available in both `/query` and `/streaming_query` endpoints
- Each user has their own list of pending approvals
- Multiple users can have pending approvals simultaneously without interference

### 2. Approval Handler Pattern

The handler creates a Future, stores it in `pending_approvals`, and blocks (`await future`) until a decision arrives via the REST endpoint or a timeout fires from `approvals.py`. The `finally` block ensures cleanup regardless of outcome. See `web_approval_handler.py` in [Complete Code](#complete-code).

**Multi-user support**: The handler reads `tool_request.client` to key approvals by user — no factory or closure needed.

**TODO**: Populate `ToolRequest.client` with `user_id` from OLS auth (`retrieve_user_id(auth)`)

### 3. REST Endpoints

#### GET `/api/approvals/pending`
- **Purpose**: Serve HTML iframe OR return JSON data (content negotiation)
- **Request Headers**: 
  - `Accept: text/html` → Returns complete HTML page
  - `Accept: application/json` OR no Accept header → Returns JSON
- **Empty response**: JSON returns minimal `{"data": []}` when empty. HTML always returns full page with polling JS so iframe keeps polling.
- **Usage**: 
  - iframe initial load: `<iframe src="/api/approvals/pending">`
  - JavaScript reload: `fetch('/api/approvals/pending')`

#### POST `/api/approvals/{request_id}/decide`
- **Purpose**: Submit approval decision
- **Request Body**: `{"approved": true|false}`
- **Side Effect**: Resolves Future in `pending_approvals`

### 4. Frontend Architecture

**iframe UI** (server-rendered, vanilla JavaScript):
- **Table**: Displays pending approvals with clickable rows
- **Modal**: Shows tool details and arguments on row click
- **Buttons**: Approve / Reject / Cancel / Reload
- **Event Flow**: `loadApprovals()` → row click → `openModal()` → button click → `decide()` → reload table

**Self-Polling iframe (Recommended)**

The iframe handles all polling internally — the parent just embeds it:

```html
<!-- Parent app: single line, no logic needed -->
<iframe src="/api/approvals/pending" width="100%" height="400px"></iframe>
```

Inside the iframe, JavaScript polls and updates automatically:

1. **On load**: `loadApprovals()` fetches pending approvals, starts polling every 2 seconds
2. **Approvals appear**: Table renders with clickable rows
3. **User decides**: POST decision → reload table
4. **Table empty**: Shows minimal empty state, continues polling in background

---

## Complete Code

### File 1: `web_approval_handler.py`

```python
"""Web-based approval handler for HTTP/iframe-based approvals.

This module provides an approval handler that uses a web UI instead of CLI.
Approvals are displayed in an iframe and submitted via REST API.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from uuid import uuid4

from approvals import ToolRequest

logger = logging.getLogger(__name__)

# Shared in-memory state
# In production, replace with OLS database for multi-instance support
pending_approvals: Dict[str, List[Dict]] = {}


async def web_approval_handler(tool_request: ToolRequest) -> bool:
    """Web-based approval handler.
    
    Creates an approval request, stores it in shared memory, and blocks
    until a decision is made via the web UI.
    
    Args:
        tool_request: Tool call requiring approval
        
    Returns:
        bool: True if approved, False if rejected
        
    Example:
        config = ToolLevelApprovalConfig(
            approval_ui_handler=web_approval_handler
        )
        approval = ToolLevelApproval(config)
    """
    request_id = str(uuid4())
    user_id = tool_request.client
    future: asyncio.Future[bool] = asyncio.Future()
    
    approval_dict = {
        'request_id': request_id,
        'tool_request': tool_request,
        'future': future,
        'created_at': datetime.now()
    }
    
    if user_id not in pending_approvals:
        pending_approvals[user_id] = []
    pending_approvals[user_id].append(approval_dict)
    
    logger.info(
        "Approval required for %s (request_id=%s, user=%s). "
        "Waiting for decision via web UI...",
        tool_request.name,
        request_id,
        user_id
    )
    
    try:
        result = await future
        logger.info(
            "Approval %s: %s",
            "granted" if result else "denied",
            tool_request.name
        )
        return result
    finally:
        # CLEANUP - Always runs, even on timeout/exception
        pending_approvals[user_id] = [
            a for a in pending_approvals.get(user_id, [])
            if a["request_id"] != request_id
        ]
        if not pending_approvals[user_id]:
            del pending_approvals[user_id]


def get_pending_approvals(user_id: str) -> list[dict]:
    """Get list of pending approvals for a specific user."""
    return [
        {
            "id": data['request_id'],
            "tool": data['tool_request'].name,
            "description": data['tool_request'].description,
            "args": data['tool_request'].args,
            "created_at": data['created_at'].isoformat()
        }
        for data in pending_approvals.get(user_id, [])
    ]


def resolve_approval(user_id: str, request_id: str, approved: bool) -> bool:
    """Resolve a pending approval request for a specific user.
    
    Returns:
        bool: True if request was found and resolved, False otherwise
    """
    for approval in pending_approvals.get(user_id, []):
        if approval['request_id'] == request_id:
            approval['future'].set_result(approved)
            logger.info("Resolved approval %s: %s", request_id, approved)
            return True
    
    logger.warning("Approval request not found: %s (user=%s)", request_id, user_id)
    return False
```

### File 2: `approval_endpoints.py`

```python
"""FastAPI endpoints for web-based approval system.

Single endpoint uses content negotiation to return HTML or JSON.
"""

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from web_approval_handler import get_pending_approvals, resolve_approval

router = APIRouter()


class ApprovalDecision(BaseModel):
    """Request body for approval decision."""
    approved: bool


@router.get("/pending")
async def get_pending(accept: Optional[str] = Header(None)):
    """Get pending approvals - returns HTML or JSON based on Accept header.
    
    Content Negotiation:
    - Accept: text/html → Returns complete HTML page for iframe
    - Accept: application/json OR no header → Returns JSON data
    """
    # TODO: get user_id from OLS auth (retrieve_user_id(auth))
    user_id = "demo-user"
    approvals = get_pending_approvals(user_id)
    
    # Empty response - lightweight for JSON polling
    if not approvals and not (accept and "text/html" in accept):
        return {"data": []}
    
    # HTML response - always includes polling JS so iframe keeps polling
    if accept and "text/html" in accept:
        return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Pending Approvals</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                   Roboto, 'Helvetica Neue', Arial, sans-serif;
                   padding: 20px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; background: white;
                         border-radius: 8px; padding: 20px;
                         box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .header { display: flex; justify-content: space-between;
                      align-items: center; margin-bottom: 20px;
                      padding-bottom: 15px; border-bottom: 2px solid #e0e0e0; }
            h1 { font-size: 24px; color: #333; }
            .reload-btn { padding: 8px 16px; background: #007bff; color: white;
                          border: none; border-radius: 4px; cursor: pointer;
                          font-size: 14px; transition: background 0.2s; }
            .reload-btn:hover { background: #0056b3; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left;
                     border-bottom: 1px solid #e0e0e0; }
            th { background: #f8f9fa; font-weight: 600; color: #555; }
            tr:hover { background: #f9f9f9; cursor: pointer; }
            td { font-size: 14px; color: #333; }
            .empty-state { text-align: center; color: #999; padding: 40px;
                           font-style: italic; }
            .overlay { display: none; position: fixed; top: 0; left: 0;
                       width: 100%; height: 100%;
                       background: rgba(0,0,0,0.5); z-index: 999; }
            .modal { display: none; position: fixed; top: 50%; left: 50%;
                     transform: translate(-50%, -50%); background: white;
                     padding: 24px; border-radius: 8px;
                     box-shadow: 0 4px 20px rgba(0,0,0,0.15); z-index: 1000;
                     min-width: 500px; max-width: 90%; max-height: 80vh;
                     overflow-y: auto; }
            .modal h2 { margin-bottom: 20px; color: #333; }
            .modal-content p { margin-bottom: 15px; line-height: 1.5; }
            .modal-content pre { background: #f4f4f4; padding: 12px;
                                  border-radius: 4px; overflow-x: auto;
                                  font-size: 13px; }
            .btn-group { margin-top: 24px; display: flex; gap: 10px;
                         justify-content: flex-end; }
            .btn { padding: 10px 20px; border: none; border-radius: 4px;
                   cursor: pointer; font-size: 14px; font-weight: 500;
                   transition: all 0.2s; }
            .btn-approve { background: #28a745; color: white; }
            .btn-approve:hover { background: #218838; }
            .btn-reject { background: #dc3545; color: white; }
            .btn-reject:hover { background: #c82333; }
            .btn-cancel { background: #6c757d; color: white; }
            .btn-cancel:hover { background: #5a6268; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Pending Approvals</h1>
                <button class="reload-btn" onclick="loadApprovals()">
                    Reload
                </button>
            </div>
            <table>
                <thead>
                    <tr><th>Tool</th><th>Description</th><th>Time</th></tr>
                </thead>
                <tbody id="approvals-body">
                    <tr><td colspan="3" class="empty-state">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="overlay" id="overlay" onclick="closeModal()"></div>
        <div class="modal" id="modal">
            <h2 id="modal-title"></h2>
            <div class="modal-content" id="modal-content"></div>
            <div class="btn-group">
                <button class="btn btn-approve" onclick="decide(true)">
                    Approve</button>
                <button class="btn btn-reject" onclick="decide(false)">
                    Reject</button>
                <button class="btn btn-cancel" onclick="closeModal()">
                    Cancel</button>
            </div>
        </div>

        <script>
            let currentId = null;

            async function loadApprovals() {
                try {
                    const res = await fetch('/api/approvals/pending');
                    const data = await res.json();
                    const tbody = document.getElementById('approvals-body');
                    tbody.innerHTML = '';
                    if (data.data && data.data.length > 0) {
                        data.data.forEach(a => {
                            const row = tbody.insertRow();
                            row.onclick = () => openModal(a);
                            row.insertCell(0).textContent = a.tool;
                            row.insertCell(1).textContent = a.description;
                            row.insertCell(2).textContent =
                                new Date(a.created_at).toLocaleString();
                        });
                    } else {
                        tbody.innerHTML =
                            '<tr><td colspan="3" class="empty-state">' +
                            'No pending approvals</td></tr>';
                    }
                } catch (e) {
                    console.error('Failed to load:', e);
                }
            }

            function openModal(a) {
                currentId = a.id;
                document.getElementById('modal-title').textContent =
                    'Approve ' + a.tool + '?';
                document.getElementById('modal-content').innerHTML =
                    '<p><strong>Tool:</strong> ' + a.tool + '</p>' +
                    '<p><strong>Description:</strong> ' + a.description + '</p>' +
                    '<p><strong>Arguments:</strong></p>' +
                    '<pre>' + JSON.stringify(a.args, null, 2) + '</pre>';
                document.getElementById('overlay').style.display = 'block';
                document.getElementById('modal').style.display = 'block';
            }

            function closeModal() {
                document.getElementById('overlay').style.display = 'none';
                document.getElementById('modal').style.display = 'none';
                currentId = null;
            }

            async function decide(approved) {
                if (!currentId) return;
                try {
                    const res = await fetch(
                        '/api/approvals/' + currentId + '/decide',
                        { method: 'POST',
                          headers: {'Content-Type': 'application/json'},
                          body: JSON.stringify({approved}) });
                    if (res.ok) { closeModal(); await loadApprovals(); }
                    else { alert('Failed. Try again.'); }
                } catch (e) {
                    console.error('Failed:', e);
                    alert('Failed. Try again.');
                }
            }

            // Initial load + poll every 2 seconds
            loadApprovals();
            setInterval(loadApprovals, 2000);
        </script>
    </body>
    </html>
    """)
    
    # Otherwise return JSON (for iframe JavaScript fetch)
    return {"data": approvals}


@router.post("/{request_id}/decide")
async def submit_decision(request_id: str, decision: ApprovalDecision):
    """Submit approval decision for a pending request."""
    # TODO: get user_id from OLS auth (retrieve_user_id(auth))
    user_id = "demo-user"
    success = resolve_approval(user_id, request_id, decision.approved)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Approval request not found: {request_id}"
        )
    
    return {
        "status": "ok",
        "request_id": request_id,
        "decision": "approved" if decision.approved else "rejected"
    }
```

### File 3: Integration into lightspeed-service

```python
# In lightspeed-service/main.py - add approval endpoints to existing app

from approval_endpoints import router as approval_router

app.include_router(
    approval_router,
    prefix="/api/approvals",
    tags=["approvals"]
)
```

### File 4: Configure approval in ols_approval_client

```python
# Switch from CLI handler to web handler

from web_approval_handler import web_approval_handler
from approvals import ToolLevelApprovalConfig, ToolLevelApproval

config = ToolLevelApprovalConfig(
    approval_ui_handler=web_approval_handler,
    approval_timeout=300,  # 5 minutes (longer for web UI)
)

approval = ToolLevelApproval(config)
```

No new dependencies required - uses existing `fastapi`, `pydantic`, and `asyncio`.

