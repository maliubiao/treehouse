import argparse
import asyncio

from .client import GenericLSPClient
from .debug import debug_console


def main():
    parser = argparse.ArgumentParser(description="LSP调试工具")
    parser.add_argument("--lsp", required=True, help="LSP服务器启动命令，例如：pylsp")
    parser.add_argument("--workspace", default=".", help="工作区路径（默认当前目录）")
    args = parser.parse_args()

    lsp_client = GenericLSPClient(lsp_command=args.lsp.split(), workspace_path=args.workspace)
    lsp_client.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(debug_console(lsp_client))
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(lsp_client.shutdown())
        loop.close()
