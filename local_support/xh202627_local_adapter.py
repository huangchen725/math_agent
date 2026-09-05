"""R1-2 显式本地适配器（CLIENT-002）。

正式入口导入图之外的本地适配器：包装项目自有 InternChatClient，为本地
入口（main.py/demo.py）显式提供 usage 记账与工具调用增强。本模块不属于
正式运行时（``user_agent.py`` 不导入它）；正式平台注入的未知 client 永远
只走三参数公开协议，运行时不做任何能力探测。

适配器协议（经宽构造器 ``ReasoningAgent(client, local_adapter=...)`` 注入）：

- ``chat(messages, temperature, max_tokens)``：三参数公开协议，附带 usage 记账。
- ``chat_with_tools(messages, temperature, max_tokens, tools)``：本地工具增强请求。
- ``read_usage()``：读取最近一次记录的 usage，供本地预算记账。
"""

from typing import Any, Dict


class LocalToolAdapter:
    """包装 InternChatClient 的显式本地适配器。"""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._last_meta: Dict[str, Any] = {}

    def _sink(self, meta: Dict[str, Any]) -> None:
        self._last_meta = meta if isinstance(meta, dict) else {}

    def chat(self, messages, temperature, max_tokens):
        """三参数公开协议请求；meta_sink 记录 usage。"""
        return self._client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            meta_sink=self._sink,
        )

    def chat_with_tools(self, messages, temperature, max_tokens, tools,
                        tool_choice: str = "auto"):
        """本地工具增强请求（仅在显式注入本适配器时使用）。"""
        return self._client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            meta_sink=self._sink,
        )

    def read_usage(self) -> Dict[str, Any]:
        """返回最近一次响应的 usage（尽力而为语义，与锚定版一致）。"""
        usage = self._last_meta.get("usage")
        return dict(usage) if isinstance(usage, dict) else {}
