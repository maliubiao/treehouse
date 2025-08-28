#!/usr/bin/env python3
"""
Common HTTP server utilities for test files
Provides a shared HTTP server implementation to replace file:// URL usage
"""

import asyncio
import shutil
import tempfile

from aiohttp import web


async def create_test_server(html_content, port=8080):
    """
    Start a simple HTTP server to serve the test HTML content

    Args:
        html_content (str): The HTML content to serve
        port (int): Port to serve on (default 8080)

    Returns:
        tuple: (server_runner, test_url) where server_runner can be used for cleanup
    """
    app = web.Application()

    async def handler(request):
        return web.Response(text=html_content, content_type="text/html")

    app.router.add_get("/", handler)
    app.router.add_get("/test.html", handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    test_url = f"http://localhost:{port}/test.html"

    return runner, test_url


async def cleanup_test_server(server_runner):
    """
    Clean up the test server

    Args:
        server_runner: The server runner returned by create_test_server
    """
    if server_runner:
        await server_runner.cleanup()


class TestServerContext:
    """
    Context manager for test server to ensure proper cleanup
    """

    def __init__(self, html_content, port=8080):
        self.html_content = html_content
        self.port = port
        self.server_runner = None
        self.test_url = None

    async def __aenter__(self):
        self.server_runner, self.test_url = await create_test_server(self.html_content, self.port)
        return self.test_url

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await cleanup_test_server(self.server_runner)


# Legacy temp file cleanup utility for migration
def cleanup_temp_dir(temp_dir):
    """
    Clean up temporary directory

    Args:
        temp_dir (str): Path to temporary directory to remove
    """
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass
