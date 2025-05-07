import asyncio
import atexit
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import Future
from logging import getLogger

from .language_id import LanguageId
from .lsp_symbol_kind import SymbolKind

logger = getLogger(__name__)


class Capabilities:
    """LSP server capabilities with validation methods"""

    def __init__(self, capabilities_dict):
        self.position_encoding = capabilities_dict.get("positionEncoding", "utf-16")
        self.text_document_sync = capabilities_dict.get("textDocumentSync")
        self.completion_provider = capabilities_dict.get("completionProvider")
        self.hover_provider = capabilities_dict.get("hoverProvider")
        self.signature_help_provider = capabilities_dict.get("signatureHelpProvider")
        self.definition_provider = capabilities_dict.get("definitionProvider")
        self.type_definition_provider = capabilities_dict.get("typeDefinitionProvider")
        self.implementation_provider = capabilities_dict.get("implementationProvider")
        self.references_provider = capabilities_dict.get("referencesProvider")
        self.document_highlight_provider = capabilities_dict.get("documentHighlightProvider")
        self.document_symbol_provider = capabilities_dict.get("documentSymbolProvider")
        self.code_action_provider = capabilities_dict.get("codeActionProvider")
        self.code_lens_provider = capabilities_dict.get("codeLensProvider")
        self.document_link_provider = capabilities_dict.get("documentLinkProvider")
        self.document_formatting_provider = capabilities_dict.get("documentFormattingProvider")
        self.document_range_formatting_provider = capabilities_dict.get("documentRangeFormattingProvider")
        self.document_on_type_formatting_provider = capabilities_dict.get("documentOnTypeFormattingProvider")
        self.rename_provider = capabilities_dict.get("renameProvider")
        self.folding_range_provider = capabilities_dict.get("foldingRangeProvider")
        self.execute_command_provider = capabilities_dict.get("executeCommandProvider")
        self.selection_range_provider = capabilities_dict.get("selectionRangeProvider")
        self.linked_editing_range_provider = capabilities_dict.get("linkedEditingRangeProvider")
        self.call_hierarchy_provider = capabilities_dict.get("callHierarchyProvider")
        self.semantic_tokens_provider = capabilities_dict.get("semanticTokensProvider")
        self.moniker_provider = capabilities_dict.get("monikerProvider")
        self.type_hierarchy_provider = capabilities_dict.get("typeHierarchyProvider")
        self.inline_value_provider = capabilities_dict.get("inlineValueProvider")
        self.inlay_hint_provider = capabilities_dict.get("inlayHintProvider")
        self.diagnostic_provider = capabilities_dict.get("diagnosticProvider")
        self.workspace_symbol_provider = capabilities_dict.get("workspaceSymbolProvider")
        self.workspace = capabilities_dict.get("workspace", {})
        self.workspace_workspace_folders = self.workspace.get("workspaceFolders", {})
        self.experimental = capabilities_dict.get("experimental")

    def supports(self, feature):
        """Check if server supports a specific feature"""
        provider_map = {
            "hover": self.hover_provider,
            "definition": self.definition_provider,
            "documentSymbol": self.document_symbol_provider,
            "completion": self.completion_provider,
            "callHierarchy": self.call_hierarchy_provider,
            "typeHierarchy": self.type_hierarchy_provider,
            "signatureHelp": self.signature_help_provider,
            "references": self.references_provider,
            "implementation": self.implementation_provider,
            "rename": self.rename_provider,
            "codeAction": self.code_action_provider,
            "workspaceFolders": self.workspace_workspace_folders.get("supported", False),
            "workspaceSymbol": self.workspace_symbol_provider,
            "textDocumentSync": self._get_text_sync_kind(),
        }
        return bool(provider_map.get(feature))

    def _get_text_sync_kind(self):
        """解析文本同步类型"""
        if isinstance(self.text_document_sync, dict):
            return self.text_document_sync.get("change")
        if isinstance(self.text_document_sync, int):
            return self.text_document_sync
        return None


class LSPFeatureError(NotImplementedError):
    """Exception raised when a feature is not supported by the server"""

    def __init__(self, feature):
        super().__init__(f"Server does not support {feature} capability")
        self.feature = feature


class GenericLSPClient:
    def __init__(self, lsp_command, workspace_path, init_params=None):
        self.workspace_path = os.path.abspath(workspace_path)
        self.lsp_command = lsp_command
        self.init_params = init_params or {}
        self.process = None
        self.stdin = None
        self.stdout = None
        self.request_id = 1
        self.response_futures = {}
        self.running = False
        self._lock = threading.Lock()
        self.capabilities = None
        self.initialized_event = threading.Event()
        self._document_versions = {}
        atexit.register(self._cleanup)

    def start(self):
        """启动LSP服务器进程"""
        try:
            self.process = subprocess.Popen(  # pylint: disable=consider-using-with
                self.lsp_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr,
                text=True,
                cwd=self.workspace_path,
                bufsize=0,
            )
            self.stdin = self.process.stdin
            self.stdout = self.process.stdout
            self.running = True

            threading.Thread(target=self._read_responses, daemon=True).start()
            self.initialize()

        except (subprocess.SubprocessError, OSError) as e:
            self._cleanup()
            logger.error("Failed to start LSP: %s", str(e))
            raise

    def initialize(self):
        """发送初始化请求"""
        default_capabilities = {
            "textDocument": {
                "synchronization": {
                    "dynamicRegistration": False,
                    "willSave": True,
                    "willSaveWaitUntil": False,
                    "didSave": True,
                },
                "hover": {"contentFormat": ["markdown", "plaintext"]},
                "documentSymbol": {
                    "hierarchicalDocumentSymbolSupport": True,
                    "symbolKind": {
                        "valueSet": [v for k, v in vars(SymbolKind).items() if k.isupper() and isinstance(v, int)]
                    },
                },
                "completion": {
                    "completionItem": {
                        "snippetSupport": False,
                        "commitCharactersSupport": True,
                        "documentationFormat": ["markdown", "plaintext"],
                    },
                    "contextSupport": True,
                },
                "definition": {"linkSupport": False},
                "typeDefinition": {"linkSupport": False},
            },
            "workspace": {
                "workspaceFolders": True,
                "fileOperations": {
                    "didCreateFiles": True,
                    "didDeleteFiles": True,
                    "didRenameFiles": True,
                },
                "symbol": {
                    "dynamicRegistration": True,
                    "symbolKind": {
                        "valueSet": [v for k, v in vars(SymbolKind).items() if k.isupper() and isinstance(v, int)]
                    },
                    "resolveSupport": {
                        "properties": [
                            "location.range",
                            "location.uri",
                            "containerName",
                        ]
                    },
                },
            },
        }

        workspace_folders = self.init_params.get(
            "workspaceFolders",
            [
                {
                    "uri": f"file://{self.workspace_path}",
                    "name": os.path.basename(self.workspace_path.rstrip(os.sep)),
                }
            ],
        )

        init_params = {
            "processId": os.getpid(),
            "rootUri": f"file://{self.workspace_path}",
            "capabilities": default_capabilities,
            "initializationOptions": {
                "hover": {"show": {"computations": True, "debug": False}},
                "completion": {"resolveTriggerCharacters": [".", ":", "@"]},
            },
            "workspaceFolders": workspace_folders,
            **self.init_params,
        }
        future = self.send_request("initialize", init_params)
        future.add_done_callback(self._handle_initialize_response)

    def _handle_initialize_response(self, future):
        """处理初始化响应并设置能力"""
        try:
            result = future.result()
            self.capabilities = Capabilities(result.get("capabilities", {}))
            self.initialized_event.set()
            logger.debug("Server capabilities initialized: %s", self.capabilities.__dict__)
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Initialize failed: %s", str(e))
            self._cleanup()

    def _check_feature_support(self, feature):
        """检查功能支持情况"""
        if not self.initialized_event.wait(timeout=5):
            raise RuntimeError("LSP client not initialized")
        if not self.capabilities.supports(feature):
            raise LSPFeatureError(feature)

    def send_request(self, method, params):
        """发送JSON-RPC请求"""
        with self._lock:
            request_id = self.request_id
            self.request_id += 1

        future = Future()
        with self._lock:
            self.response_futures[request_id] = future

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        self._send_message(request)
        return future

    def send_notification(self, method, params):
        """发送JSON-RPC通知"""
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        self._send_message(notification)

    def _send_message(self, message):
        """发送原始消息"""
        try:
            message_str = json.dumps(message)
            content = f"Content-Length: {len(message_str)}\r\n\r\n{message_str}"
            self.stdin.write(content)
            self.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error("Failed to send message: %s", str(e))
            self._cleanup()

    def _read_responses(self):
        """持续读取服务器响应"""
        try:
            while self.running:
                headers = {}
                while True:
                    line = self.stdout.readline().strip()
                    if not line:
                        break
                    if ": " in line:
                        name, value = line.split(": ", 1)
                        headers[name.lower()] = value

                if "content-length" not in headers:
                    break
                content_length = int(headers["content-length"])
                content = self.stdout.read(content_length)
                try:
                    msg = json.loads(content)
                    self._handle_response(msg)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse JSON response: %s", str(e))

        except (OSError, RuntimeError) as e:
            logger.error("Response reading thread crashed: %s", str(e))
            self._cleanup()

    def _handle_response(self, response):
        """处理服务器响应"""
        if "id" in response:
            request_id = response["id"]
            with self._lock:
                future = self.response_futures.pop(request_id, None)
            if future:
                if "result" in response:
                    future.set_result(response["result"])
                elif "error" in response:
                    future.set_exception(Exception(json.dumps(response["error"])))
        else:
            logger.debug("Received notification: %s", response.get("method"))

    async def shutdown(self):
        """优雅关闭LSP连接"""
        if not self.running:
            return

        try:
            await asyncio.wrap_future(self.send_request("shutdown", None))
            self.send_notification("exit", None)

            if self.process:
                await asyncio.get_event_loop().run_in_executor(None, self.process.wait)
        except (OSError, RuntimeError) as e:
            logger.error("Shutdown failed: %s", str(e))
        finally:
            self._cleanup()

    async def force_down(self):
        self.process.terminate()
        self.process.wait(timeout=1)
        self.process = None

    def _cleanup(self):
        """清理资源"""
        self.running = False
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except (OSError, RuntimeError) as e:
                logger.error("Cleanup error: %s", str(e))
            finally:
                self.process.stdout.close()
                self.process.stdin.close()
            with self._lock:
                for future in self.response_futures.values():
                    if not future.done():
                        future.set_exception(asyncio.CancelledError("LSP client shutdown"))
                self.response_futures.clear()
        for pipe in [
            self.stdin,
            self.stdout,
            self.process.stderr if self.process else None,
        ]:
            try:
                if pipe:
                    pipe.close()
            except (OSError, RuntimeError) as e:
                logger.debug("Error closing pipe: %s", str(e))

    async def get_document_symbols(self, file_path):
        """获取文档符号"""
        self._check_feature_support("documentSymbol")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except IOError as e:
            logger.error("Failed to read file: %s", str(e))
            return None

        language_id = LanguageId.get_language_id(file_path)
        self.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": f"file://{file_path}",
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )

        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/documentSymbol",
                    {"textDocument": {"uri": f"file://{file_path}"}},
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get document symbols: %s", str(e))
            return None

    def did_change(self, file_path: str, content: str):
        """发送文档变更通知（全量更新）"""
        self._check_feature_support("textDocumentSync")
        sync_kind = self.capabilities._get_text_sync_kind()

        if sync_kind != 1:  # 1表示Full同步模式
            raise LSPFeatureError(f"textDocumentSync Full (current sync kind: {sync_kind})")

        # 更新文档版本号
        version = self._document_versions.get(file_path, 1) + 1
        self._document_versions[file_path] = version

        params = {
            "textDocument": {"uri": f"file://{file_path}", "version": version},
            "contentChanges": [{"text": content}],
        }
        self.send_notification("textDocument/didChange", params)
        logger.debug("Sent didChange notification for %s (version %d)", file_path, version)

    async def get_workspace_symbols(self, query):
        """获取工作区符号"""
        self._check_feature_support("workspaceSymbol")
        try:
            return await asyncio.wrap_future(self.send_request("workspace/symbol", {"query": query}))
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get workspace symbols: %s", str(e))
            return None

    async def get_hover_info(self, file_path, line, character):
        """获取悬停信息"""
        self._check_feature_support("hover")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/hover",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get hover info: %s", str(e))
            return None

    async def get_completion(self, file_path, line, character, context=None):
        """获取代码补全（增强元数据解析）"""
        self._check_feature_support("completion")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/completion",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                        "context": context or {},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get completion: %s", str(e))
            return None

    async def get_definition(self, file_path, line, character):
        """获取符号定义位置"""
        self._check_feature_support("definition")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get definition: %s", str(e))
            return None

    async def prepare_call_hierarchy(self, file_path, line, character):
        """准备调用层次结构"""
        self._check_feature_support("callHierarchy")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/prepareCallHierarchy",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to prepare call hierarchy: %s", str(e))
            return None

    async def get_incoming_calls(self, item):
        """获取传入调用"""
        self._check_feature_support("callHierarchy")
        try:
            return await asyncio.wrap_future(self.send_request("callHierarchy/incomingCalls", {"item": item}))
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get incoming calls: %s", str(e))
            return None

    async def get_outgoing_calls(self, item):
        """获取传出调用"""
        self._check_feature_support("callHierarchy")
        try:
            return await asyncio.wrap_future(self.send_request("callHierarchy/outgoingCalls", {"item": item}))
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get outgoing calls: %s", str(e))
            return None

    async def prepare_type_hierarchy(self, file_path, line, character):
        """准备类型层次结构"""
        self._check_feature_support("typeHierarchy")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/prepareTypeHierarchy",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to prepare type hierarchy: %s", str(e))
            return None

    async def get_supertypes(self, item):
        """获取超类型"""
        self._check_feature_support("typeHierarchy")
        try:
            return await asyncio.wrap_future(self.send_request("typeHierarchy/supertypes", {"item": item}))
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get supertypes: %s", str(e))
            return None

    async def get_subtypes(self, item):
        """获取子类型"""
        self._check_feature_support("typeHierarchy")
        try:
            return await asyncio.wrap_future(self.send_request("typeHierarchy/subtypes", {"item": item}))
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get subtypes: %s", str(e))
            return None

    async def get_signature_help(self, file_path, line, character):
        """获取函数签名信息"""
        self._check_feature_support("signatureHelp")
        try:
            return await asyncio.wrap_future(
                self.send_request(
                    "textDocument/signatureHelp",
                    {
                        "textDocument": {"uri": f"file://{file_path}"},
                        "position": {"line": line - 1, "character": character},
                    },
                )
            )
        except (OSError, RuntimeError) as e:
            logger.error("Failed to get signature help: %s", str(e))
            return None
