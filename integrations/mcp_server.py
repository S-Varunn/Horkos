import asyncio
import json
import sys
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from db.database import Database
from db.models import Commitment, CommitmentStatus
from config import settings

logger = logging.getLogger("CommitmentRadar.MCP")

MCP_TOOLS = [
    {
        "name": "list_active_commitments",
        "description": "List all active, pending micro-commitments across the workspace or for a specific user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Optional Discord user ID to filter commitments for a specific person"
                }
            }
        }
    },
    {
        "name": "resolve_commitment",
        "description": "Mark an active micro-commitment as completed",
        "inputSchema": {
            "type": "object",
            "properties": {
                "commitment_id": {
                    "type": "integer",
                    "description": "The numeric ID of the commitment to resolve"
                }
            },
            "required": ["commitment_id"]
        }
    },
    {
        "name": "schedule_commitment",
        "description": "Directly record and schedule a new micro-commitment",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_title": {"type": "string", "description": "Actionable task description"},
                "timeframe": {"type": "string", "description": "Deadline description or ISO timestamp"},
                "recipient": {"type": "string", "description": "Target recipient or team"},
                "user_name": {"type": "string", "description": "Name of the person who committed"}
            },
            "required": ["task_title", "timeframe"]
        }
    },
    {
        "name": "export_commitments",
        "description": "Export active commitments in Markdown, JSON, or Todoist format",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json", "todoist"],
                    "description": "The export format",
                    "default": "markdown"
                },
                "user_id": {
                    "type": "string",
                    "description": "Optional user ID to filter exports"
                }
            }
        }
    }
]


def format_commitments_markdown(commitments: List[Commitment], title: str = "Active Commitments") -> str:
    """Formats commitments into a GitHub Flavored Markdown checklist."""
    if not commitments:
        return f"### 🎯 {title}\n\n*No active commitments found.*"

    lines = [f"### 🎯 {title} ({len(commitments)})\n"]
    for c in commitments:
        deadline_str = c.deadline_utc.strftime("%Y-%m-%d %H:%M UTC") if c.deadline_utc else "Flexible"
        recip_str = f" for **@{c.recipient}**" if c.recipient else ""
        gcal_str = f" • [Calendar Link]({c.calendar_event_link})" if c.calendar_event_link else ""
        lines.append(f"- [ ] **#{c.id} {c.task_title}**{recip_str} (Due: `{deadline_str}`){gcal_str}")

    return "\n".join(lines)


def format_commitments_todoist(commitments: List[Commitment]) -> List[Dict[str, Any]]:
    """Formats commitments for 1-click import into Todoist API."""
    tasks = []
    for c in commitments:
        tasks.append({
            "content": f"[Commitment #{c.id}] {c.task_title}" + (f" (for {c.recipient})" if c.recipient else ""),
            "description": f"Captured ambiently from Discord: \"{c.raw_text}\"",
            "due_datetime": c.deadline_utc.isoformat() + "Z" if c.deadline_utc else None,
            "priority": 3
        })
    return tasks


class MCPServer:
    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database(settings.database_path)

    async def handle_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executes an MCP tool call and returns standard JSON-RPC tool result."""
        if name == "list_active_commitments":
            user_id = arguments.get("user_id")
            if user_id:
                commitments = await self.db.get_active_commitments_for_user(user_id)
            else:
                commitments = await self.db.get_all_active_commitments()

            data = [
                {
                    "id": c.id,
                    "task_title": c.task_title,
                    "recipient": c.recipient,
                    "user_name": c.user_name,
                    "deadline_utc": c.deadline_utc.isoformat() if c.deadline_utc else None,
                    "relative_deadline": c.relative_deadline_text,
                    "status": c.status.value if hasattr(c.status, "value") else c.status,
                    "calendar_event_link": c.calendar_event_link
                }
                for c in commitments
            ]
            return {"commitments": data, "count": len(data)}

        elif name == "resolve_commitment":
            cid = arguments.get("commitment_id")
            if not cid:
                return {"success": False, "error": "commitment_id is required"}

            updated = await self.db.update_status(cid, CommitmentStatus.COMPLETED)
            return {"success": updated, "commitment_id": cid, "new_status": "COMPLETED"}

        elif name == "schedule_commitment":
            task_title = arguments.get("task_title")
            timeframe = arguments.get("timeframe")
            recipient = arguments.get("recipient")
            user_name = arguments.get("user_name", "User")
            user_id = arguments.get("user_id", "mcp_user")

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            commitment = Commitment(
                user_id=user_id,
                user_name=user_name,
                channel_id="mcp",
                message_id="mcp",
                raw_text=f"Scheduled via MCP: {task_title} {timeframe}",
                task_title=task_title,
                recipient=recipient,
                deadline_utc=now_utc,
                relative_deadline_text=timeframe,
                context_snippet="Created via Model Context Protocol (MCP)",
                status=CommitmentStatus.PENDING
            )
            saved = await self.db.add_commitment(commitment)
            return {"success": True, "commitment_id": saved.id, "task_title": saved.task_title}

        elif name == "export_commitments":
            export_fmt = arguments.get("format", "markdown").lower()
            user_id = arguments.get("user_id")

            if user_id:
                commitments = await self.db.get_active_commitments_for_user(user_id)
            else:
                commitments = await self.db.get_all_active_commitments()

            if export_fmt == "markdown":
                return {"format": "markdown", "content": format_commitments_markdown(commitments)}
            elif export_fmt == "todoist":
                return {"format": "todoist", "tasks": format_commitments_todoist(commitments)}
            else:
                data = [
                    {
                        "id": c.id,
                        "task": c.task_title,
                        "recipient": c.recipient,
                        "user": c.user_name,
                        "deadline": c.deadline_utc.isoformat() if c.deadline_utc else None
                    }
                    for c in commitments
                ]
                return {"format": "json", "commitments": data}

        return {"error": f"Unknown tool: {name}"}

    async def run_stdio(self):
        """Runs standard MCP JSON-RPC 2.0 loop over stdin/stdout."""
        await self.db.init_db()
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                request = json.loads(line.decode().strip())
                req_id = request.get("id")
                method = request.get("method")

                if method == "tools/list":
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}
                elif method == "tools/call":
                    params = request.get("params", {})
                    name = params.get("name")
                    args = params.get("arguments", {})
                    result = await self.handle_call(name, args)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}}
                else:
                    response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}

                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = MCPServer()
    asyncio.run(server.run_stdio())
