import asyncio
import json
import logging
import os
import shlex
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class MCPClientManager:
    def __init__(self, server_url: str = "", transport: str = "streamable_http",
                 verbose: bool = False, env: Optional[dict] = None,
                 headers: Optional[dict] = None):
        self.server_url = server_url.rstrip("/") if transport != "stdio" else server_url
        self.transport = transport
        self.verbose = verbose
        self.env: dict = dict(env) if env else {}
        self.headers: dict = dict(headers) if headers else {}

        self._connected = False
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._http_client: Optional[httpx.AsyncClient] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._read_line_lock = asyncio.Lock()
        self._sse_endpoint: Optional[str] = None

        self._tools_cache: list[dict] = []
        self._resources_cache: list[dict] = []
        self._resource_templates_cache: list[dict] = []
        self._last_error: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._connected

    def _log(self, msg: str):
        if self.verbose:
            print(f"[MCP] {msg}")
        logger.info(msg)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def connect(self) -> bool:
        if not self.server_url:
            self._log("No MCP address configured, MCP client disabled")
            return False

        async with self._lock:
            if self._connected:
                return True
            try:
                if self.transport == "stdio":
                    ok = await self._connect_stdio()
                else:
                    ok = await self._connect_http()
                return ok
            except Exception as e:
                self._last_error = str(e)
                self._log(f"Failed to connect to MCP server: {e}")
                self._connected = False
                self._sse_endpoint = None
                self._tools_cache.clear()
                self._resources_cache.clear()
                self._resource_templates_cache.clear()
                await self._cleanup_resources()
                return False

    async def _connect_http(self) -> bool:
        self._http_client = httpx.AsyncClient(timeout=10.0, headers=self.headers)
        try:
            await self._initialize_http()
            self._connected = True
            self._log(f"Connected to MCP server at {self.server_url}")
            await self._refresh_caches()
            return True
        except Exception:
            await self._cleanup_resources()
            raise

    async def _connect_stdio(self) -> bool:
        try:
            parts = shlex.split(self.server_url)
        except ValueError:
            raise Exception(f"Invalid stdio command: {self.server_url}")
        if not parts:
            raise Exception("Empty stdio command")

        self._log(f"Starting stdio process: {parts}")
        process_env = {**os.environ, **(self.env or {})}
        self._process = await asyncio.create_subprocess_exec(
            parts[0], *parts[1:],
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
        )
        asyncio.create_task(self._read_stderr())

        try:
            await self._init_stdio()
            self._connected = True
            self._log(f"Stdio MCP process started (pid={self._process.pid})")
            await self._refresh_caches()
            return True
        except Exception:
            await self._cleanup_resources()
            raise

    async def _read_stderr(self):
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._log(f"[stderr] {text}")
        except Exception:
            pass

    async def disconnect(self):
        async with self._lock:
            self._connected = False
            self._sse_endpoint = None
            self._tools_cache.clear()
            self._resources_cache.clear()
            self._resource_templates_cache.clear()
            await self._cleanup_resources()

    async def _cleanup_resources(self):
        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        if self._process:
            proc, self._process = self._process, None
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
            except Exception:
                pass

    async def ensure_connected(self) -> bool:
        if self._connected:
            if self.transport == "stdio":
                if self._process and self._process.returncode is None:
                    return True
                self._log("Stdio process died, reconnecting")
                self._connected = False
            else:
                if self._http_client is not None:
                    return True
        return await self.connect()

    async def _initialize_http(self):
        if self.transport == "sse":
            await self._init_sse()
        else:
            await self._init_streamable_http()

    async def _init_streamable_http(self):
        await self._jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-chat-mcp-client", "version": "1.0.0"},
        })

    async def _init_sse(self):
        sse_url = self.server_url + ("/sse" if not self.server_url.endswith("/sse") else "")
        async with self._http_client.stream("GET", sse_url) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("event: endpoint"):
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    self._sse_endpoint = data.strip()
                    self._log(f"SSE endpoint: {self._sse_endpoint}")
                    break
                if line and not line.startswith(":"):
                    self._sse_endpoint = line.strip()
                    self._log(f"SSE endpoint: {self._sse_endpoint}")
                    break
            if not self._sse_endpoint:
                raise Exception("No endpoint received from SSE server")

        await self._jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-chat-mcp-client", "version": "1.0.0"},
        })

    async def _init_stdio(self):
        await self._jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-chat-mcp-client", "version": "1.0.0"},
        })

    async def _jsonrpc(self, method: str, params: Optional[dict] = None) -> dict:
        if self.transport == "stdio":
            return await self._jsonrpc_stdio(method, params)
        else:
            return await self._jsonrpc_http(method, params)

    async def _jsonrpc_http(self, method: str, params: Optional[dict] = None) -> dict:
        if not self._http_client:
            raise Exception("MCP HTTP client not initialized")

        rid = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params or {},
        }

        url = self._sse_endpoint if self.transport == "sse" else self.server_url
        self._log(f"JSON-RPC -> {method} [{rid}]")

        resp = await self._http_client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=30.0,
        )

        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            return await self._parse_sse_response(resp)
        elif "application/json" in ct:
            data = resp.json()
            if "error" in data:
                err = data["error"]
                msg = err if isinstance(err, str) else err.get("message", str(err))
                raise Exception(f"MCP error: {msg}")
            return data.get("result", data)
        else:
            text = resp.text
            try:
                data = json.loads(text)
                if "error" in data:
                    err = data["error"]
                    msg = err if isinstance(err, str) else err.get("message", str(err))
                    raise Exception(f"MCP error: {msg}")
                return data.get("result", data)
            except json.JSONDecodeError:
                raise Exception(f"Unexpected MCP response: {text[:200]}")

    async def _jsonrpc_stdio(self, method: str, params: Optional[dict] = None) -> dict:
        proc = self._process
        if not proc or proc.returncode is not None:
            raise Exception("MCP stdio process not running")
        if not proc.stdin or not proc.stdout:
            raise Exception("MCP stdio pipes not available")

        rid = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
            "params": params or {},
        }

        self._log(f"JSON-RPC (stdio) -> {method} [{rid}]")

        async with self._read_line_lock:
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            proc.stdin.write(line.encode("utf-8"))
            await proc.stdin.drain()

            try:
                response_line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=60.0
                )
            except asyncio.TimeoutError:
                raise Exception(f"Stdio request timed out for method '{method}'")

            if not response_line:
                raise Exception("MCP stdio process closed stdout")

        try:
            data = json.loads(response_line.decode("utf-8"))
        except json.JSONDecodeError:
            raise Exception(f"Invalid JSON from stdio: {response_line[:200]}")

        if "error" in data:
            raise Exception(f"MCP error: {data['error'].get('message', data['error'])}")
        return data.get("result", data)

    async def _parse_sse_response(self, response: httpx.Response) -> dict:
        result_data = None
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                try:
                    data = json.loads(data_str)
                    if isinstance(data, dict):
                        if "error" in data:
                            raise Exception(f"MCP error: {data['error'].get('message', data['error'])}")
                        if "result" in data:
                            result_data = data["result"]
                        elif data.get("jsonrpc") == "2.0":
                            result_data = data
                except json.JSONDecodeError:
                    self._log(f"SSE non-JSON data: {data_str[:100]}")
        if result_data is None:
            raise Exception("No valid JSON-RPC result in SSE stream")
        return result_data

    async def _refresh_caches(self):
        if not self._connected:
            return
        try:
            result = await self._jsonrpc("tools/list", {})
            tools = result.get("tools", [])
            self._tools_cache = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
            self._log(f"Cached {len(self._tools_cache)} tools")
        except Exception as e:
            self._log(f"Failed to list tools: {e}")
            self._tools_cache = []

        try:
            result = await self._jsonrpc("resources/list", {})
            resources = result.get("resources", [])
            self._resources_cache = [
                {"uri": r.get("uri", ""), "name": r.get("name", ""),
                 "description": r.get("description", "")}
                for r in resources
            ]
            self._log(f"Cached {len(self._resources_cache)} resources")
        except Exception as e:
            self._log(f"Failed to list resources: {e}")
            self._resources_cache = []

        try:
            result = await self._jsonrpc("resources/templates/list", {})
            templates = result.get("resourceTemplates", [])
            self._resource_templates_cache = [
                {"uriTemplate": t.get("uriTemplate", ""), "name": t.get("name", ""),
                 "description": t.get("description", "")}
                for t in templates
            ]
            self._log(f"Cached {len(self._resource_templates_cache)} resource templates")
        except Exception as e:
            self._log(f"Failed to list resource templates: {e}")
            self._resource_templates_cache = []

    async def refresh_tools(self):
        if not self._connected:
            return
        async with self._lock:
            try:
                result = await self._jsonrpc("tools/list", {})
                tools = result.get("tools", [])
                self._tools_cache = [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "inputSchema": t.get("inputSchema", {"type": "object", "properties": {}}),
                    }
                    for t in tools
                ]
                self._log(f"Refreshed {len(self._tools_cache)} tools")
            except Exception as e:
                self._log(f"Failed to refresh tools: {e}")

    def get_cached_tools(self) -> list[dict]:
        return list(self._tools_cache)

    def get_cached_resources(self) -> list[dict]:
        return list(self._resources_cache)

    def get_cached_resource_templates(self) -> list[dict]:
        return list(self._resource_templates_cache)

    def tools_to_openai_format(self) -> list[dict]:
        tools = []
        for t in self._tools_cache:
            schema = t.get("inputSchema", {"type": "object", "properties": {}})
            cleaned_schema = {"type": "object", "properties": schema.get("properties", {}),
                              "required": schema.get("required", [])}
            if "additionalProperties" in schema:
                cleaned_schema["additionalProperties"] = schema["additionalProperties"]

            tool_def = {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": cleaned_schema,
                },
            }
            tools.append(tool_def)
        return tools

    def get_tools_description_for_prompt(self) -> str:
        if not self._tools_cache:
            return ""

        lines = ["Available tools (call via function calling):"]
        for t in self._tools_cache:
            desc = t.get("description", "No description")
            schema = t.get("inputSchema", {})
            props = schema.get("properties", {})
            params = ", ".join(props.keys()) if props else "none"
            lines.append(f"  - {t['name']}: {desc} (params: {params})")
        return "\n".join(lines)

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if not self._connected:
            return {"name": name, "arguments": arguments, "error": "MCP client not connected"}

        try:
            self._log(f"Calling tool: {name} with args: {json.dumps(arguments)[:200]}")
            result = await self._jsonrpc("tools/call", {
                "name": name,
                "arguments": arguments,
            })

            content_blocks = result.get("content", [])
            contents = []
            for block in content_blocks:
                if block.get("type") == "text":
                    contents.append({"type": "text", "text": block.get("text", "")})
                elif block.get("type") == "image":
                    contents.append({"type": "image", "mimeType": block.get("mimeType", "")})
                elif block.get("type") == "resource":
                    contents.append({"type": "resource", "uri": block.get("uri", ""),
                                     "text": block.get("text", "")})

            out = {
                "name": name,
                "arguments": arguments,
                "content": contents,
                "structuredContent": result.get("structuredContent"),
                "isError": result.get("isError", False),
            }
            if out["isError"] or result.get("isError"):
                out["error"] = True
            return out
        except Exception as e:
            self._log(f"Tool call '{name}' failed: {e}")
            return {"name": name, "arguments": arguments, "error": str(e)}

    async def read_resource(self, uri: str) -> dict:
        if not self._connected:
            return {"uri": uri, "error": "MCP client not connected"}

        try:
            result = await self._jsonrpc("resources/read", {"uri": uri})
            content_blocks = result.get("contents", [])
            contents = []
            for block in content_blocks:
                if "text" in block:
                    contents.append({"type": "text", "text": block["text"]})
                elif "mimeType" in block:
                    contents.append({"type": "resource", "uri": block.get("uri", ""),
                                     "mimeType": block.get("mimeType", "")})
            return {"uri": uri, "contents": contents}
        except Exception as e:
            self._log(f"Read resource '{uri}' failed: {e}")
            return {"uri": uri, "error": str(e)}

    async def reconfigure(self, server_url: str, transport: str = "streamable_http",
                          headers: Optional[dict] = None) -> bool:
        self._log(f"Reconfiguring MCP: url={server_url}, transport={transport}")
        await self.disconnect()
        if transport == "stdio":
            self.server_url = server_url
        else:
            self.server_url = server_url.rstrip("/") if server_url else ""
        self.transport = transport or "streamable_http"
        if headers is not None:
            self.headers = dict(headers)
        self._last_error = None

        if not self.server_url:
            self._log("Empty address, MCP disabled")
            return False

        return await self.connect()

    def get_status(self) -> dict:
        masked_headers = {k: "***" for k in self.headers}
        return {
            "connected": self._connected,
            "server_url": self.server_url or "",
            "transport": self.transport,
            "env": dict(self.env),
            "headers": masked_headers,
            "tools_count": len(self._tools_cache),
            "tools": self.get_cached_tools(),
            "resources_count": len(self._resources_cache),
            "resources": self.get_cached_resources(),
            "templates_count": len(self._resource_templates_cache),
            "templates": self.get_cached_resource_templates(),
            "last_error": self._last_error,
        }
