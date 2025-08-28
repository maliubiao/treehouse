#!/usr/bin/env python3
"""
HTTP version of the MCP server that provides Python code tracing capabilities.
This server implements the Model Context Protocol over HTTP and exposes
the same tracer tools as the STDIO version.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Third-party imports
try:
    import uvicorn
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError:
    print("FastAPI and uvicorn are required for HTTP MCP server")
    print("Install with: pip install fastapi uvicorn")
    sys.exit(1)

# Import the core MCP server logic
from tracer_mcp_server import TracerMCPServer

# Configure logging for HTTP server
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("http_tracer_mcp_server.log"), logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)


class HTTPTracerMCPServer:
    """HTTP version of the MCP server with tracing capabilities."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host = host
        self.port = port

        # Initialize the core MCP server
        self.mcp_server = TracerMCPServer()

        # Initialize FastAPI
        self.app = FastAPI(
            title="Tracer MCP Server",
            description="HTTP version of the Model Context Protocol server with Python tracing capabilities",
            version=self.mcp_server.server_info["version"],
        )

        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Setup routes
        self._setup_routes()

    def _setup_routes(self):
        """Setup HTTP routes for MCP protocol."""

        @self.app.get("/")
        async def root():
            """Root endpoint with server information."""
            return {
                "message": "Tracer MCP Server (HTTP)",
                "version": self.mcp_server.server_info["version"],
                "endpoints": {"mcp": "/mcp", "health": "/health"},
            }

        @self.app.get("/health")
        async def health():
            """Health check endpoint."""
            return {"status": "healthy", "server": self.mcp_server.server_info}

        @self.app.post("/mcp")
        async def handle_mcp_request(request: Request):
            """Main MCP protocol endpoint."""
            try:
                # Parse JSON-RPC request
                body = await request.json()

                # Log incoming request
                logger.debug(f"Received MCP request: {body.get('method', 'unknown')}")

                # Process the request using the core MCP server
                response = await self._handle_mcp_message(body)

                return JSONResponse(content=response)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in request: {e}")
                return JSONResponse(
                    status_code=400,
                    content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                )
            except Exception as e:
                logger.error(f"Error handling MCP request: {e}", exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={
                        "jsonrpc": "2.0",
                        "id": body.get("id") if "body" in locals() else None,
                        "error": {"code": -32603, "message": "Internal error"},
                    },
                )

    async def _handle_mcp_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an MCP message using the core server logic."""
        try:
            request_id = message.get("id")
            method = message.get("method")
            params = message.get("params", {})

            logger.debug(f"Processing MCP method: {method}")

            # Route to appropriate handler
            if method == "initialize":
                result = self.mcp_server.handle_initialize(params)
            elif method == "tools/list":
                result = self.mcp_server.handle_tools_list()
            elif method == "tools/call":
                # Use the async version for better performance
                result = await self.mcp_server.handle_tools_call_async(params)
            else:
                result = {"error": f"Unknown method: {method}"}

            return {"jsonrpc": "2.0", "id": request_id, "result": result}

        except Exception as e:
            logger.error(f"Error processing MCP message: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32603, "message": str(e)},
            }

    async def run_async(self):
        """Run the HTTP server asynchronously."""
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)

        logger.info(f"Starting HTTP Tracer MCP Server on {self.host}:{self.port}")
        logger.info(f"MCP endpoint: http://{self.host}:{self.port}/mcp")

        await server.serve()

    def run(self):
        """Run the HTTP server synchronously."""
        asyncio.run(self.run_async())


def main() -> None:
    """Main entry point for HTTP MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="HTTP Tracer MCP Server")
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to (default: 8000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create and run the HTTP server
    server = HTTPTracerMCPServer(host=args.host, port=args.port)

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
    except Exception as e:
        logger.critical(f"Server error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
