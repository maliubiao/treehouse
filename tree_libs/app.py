import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

# 依赖于`tree.py`中的核心功能和配置
from tree import (
    GLOBAL_PROJECT_CONFIG,
    GenericLSPClient,
    ProjectConfig,
    SymbolTrie,
    start_lsp_client_once,
)


# --- Pydantic Models ---
class MatchResult(BaseModel):
    line: int
    column_range: tuple[int, int]
    text: str


class FileSearchResult(BaseModel):
    file_path: str
    matches: list[MatchResult]


class FileSearchResults(BaseModel):
    results: list[FileSearchResult]

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "FileSearchResults":
        return cls.model_validate_json(json_str)


logger = logging.getLogger(__name__)


# --- State Management ---
class WebServiceState:
    """持有一个Web服务的共享状态。"""

    def __init__(self, config: ProjectConfig):
        self.symbol_trie = SymbolTrie(case_sensitive=True)  # for global symbols
        self.file_symbol_trie = SymbolTrie(case_sensitive=True)  # for file-specific symbols
        self.file_parser_info_cache: Dict[str, Any] = {}
        self.symbol_cache: Dict[str, Any] = {}
        self.lock = threading.Lock()
        self.config: ProjectConfig = config
        self._lsp_client: Optional[GenericLSPClient] = None

    def initialize_symbols(self, symbols_dict: Dict[str, Any]) -> None:
        """根据给定的字典初始化或重新初始化全局符号前缀树。"""
        with self.lock:
            self.symbol_trie = SymbolTrie.from_symbols(symbols_dict, case_sensitive=True)

    def get_lsp_client(self, file_path: str) -> GenericLSPClient:
        """为给定的文件路径获取或创建一个LSP客户端。"""
        with self.lock:
            # This uses the caching mechanism within start_lsp_client_once
            return start_lsp_client_once(self.config, file_path)


def get_service_state(request: Request) -> WebServiceState:
    """FastAPI dependency to get the service state."""
    return request.app.state.web_service_state


# --- FastAPI App Factory ---
def create_app() -> FastAPI:
    """创建并配置FastAPI应用实例的工厂函数。"""

    # 导入Web处理逻辑
    from . import web_handlers

    app = FastAPI(title="Code Analysis Service", version="1.0.0")

    # 使用从`tree.py`加载的全局项目配置来初始化服务状态
    app.state.web_service_state = WebServiceState(config=GLOBAL_PROJECT_CONFIG)

    # --- API Endpoints ---

    @app.get("/complete")
    async def route_symbol_completion(
        prefix: str = Query(..., min_length=1),
        max_results: int = 10,
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_symbol_completion(prefix, max_results, state)

    @app.get("/symbol_content")
    async def route_get_symbol_content(
        symbol_path: str = Query(..., min_length=1),
        json_format: bool = False,
        lsp_enabled: bool = False,
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_get_symbol_content(symbol_path, json_format, lsp_enabled, state)

    @app.post("/lsp/didChange")
    async def route_lsp_file_didChange(
        file_path: str = Form(...),
        content: str = Form(...),
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_lsp_did_change(file_path, content, state)

    @app.post("/search-to-symbols")
    async def route_search_to_symbols(
        results: FileSearchResults = Body(...),
        max_context_size: int = Query(default=16384),
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_search_to_symbols(results, max_context_size, state)

    @app.get("/complete_realtime")
    async def route_symbol_completion_realtime(
        prefix: str = Query(..., min_length=1),
        max_results: int = 10,
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_symbol_completion_realtime(prefix, max_results, state)

    @app.get("/complete_simple")
    async def route_symbol_completion_simple(
        prefix: str = Query(..., min_length=1),
        max_results: int = 10,
        state: WebServiceState = Depends(get_service_state),
    ):
        return await web_handlers.handle_symbol_completion_simple(prefix, max_results, state)

    return app
