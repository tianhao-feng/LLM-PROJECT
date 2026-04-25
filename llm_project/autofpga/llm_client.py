import os
import time
from dataclasses import dataclass

import requests


DEFAULT_SYSTEM_PROMPT = (
    "你是一个顶级的 FPGA 开发专家。绝对禁止输出人类对话文本，请严格按照指令格式作答，"
    "输出代码时必须包裹在 ``` 代码块中。"
)


@dataclass
class LLMSettings:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    api_key: str = ""
    temperature: float = 0.1
    timeout: int = 300
    max_retries: int = 2
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_base_url: str = "http://localhost:11434"
    embedding_api_key_env: str = ""
    embedding_api_key: str = ""
    embedding_timeout: int = 30


class LLMClient:
    def __init__(self, settings=None):
        self.settings = settings or LLMSettings()

    def chat(self, prompt):
        provider = self.settings.provider.lower()
        if provider in {"deepseek", "openai", "openai_compatible", "cloud"}:
            print(f">>> 等待云端大模型推理: {self.settings.model}")
            return self._chat_openai_compatible(prompt)
        if provider == "ollama":
            print(f">>> 等待本地 Ollama 模型推理: {self.settings.model}")
            return self._chat_ollama(prompt)
        return f"API 报错: 未支持的 LLM provider: {self.settings.provider}"

    def embedding(self, text, model=None):
        provider = self.settings.embedding_provider.lower()
        if provider == "ollama":
            return self._embedding_ollama(text, model or self.settings.embedding_model)
        if provider in {"openai", "openai_compatible", "cloud"}:
            return self._embedding_openai_compatible(text, model or self.settings.embedding_model)
        if provider in {"none", "disabled", ""}:
            return []
        return []

    def _chat_openai_compatible(self, prompt):
        url = self._join_url(self.settings.base_url, "/chat/completions")
        headers = {"Content-Type": "application/json"}
        api_key = self._resolve_api_key(self.settings.api_key, self.settings.api_key_env)
        if not api_key:
            return f"API 报错: 未配置 API Key，请设置环境变量 {self.settings.api_key_env} 或在配置中提供 llm_api_key。"
        headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self.settings.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.settings.temperature,
        }
        result = self._post_json(url, payload, headers=headers, timeout=self.settings.timeout)
        if "error" in result:
            return f"API 报错: {result['error']}"
        try:
            return result["choices"][0]["message"]["content"]
        except Exception as exc:
            return f"API 报错: 云端响应格式异常: {exc}; raw={str(result)[:500]}"

    def _chat_ollama(self, prompt):
        url = self._join_url(self.settings.base_url, "/api/chat")
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self.settings.system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": self.settings.temperature},
        }
        result = self._post_json(url, payload, timeout=self.settings.timeout)
        if "error" in result:
            return f"API 报错: {result['error']}"
        try:
            return result["message"]["content"]
        except Exception as exc:
            return f"API 报错: Ollama 响应格式异常: {exc}; raw={str(result)[:500]}"

    def _embedding_ollama(self, text, model):
        url = self._join_url(self.settings.embedding_base_url, "/api/embeddings")
        result = self._post_json(url, {"model": model, "prompt": text}, timeout=self.settings.embedding_timeout)
        if "error" in result:
            return []
        emb = result.get("embedding", [])
        return emb if isinstance(emb, list) else []

    def _embedding_openai_compatible(self, text, model):
        url = self._join_url(self.settings.embedding_base_url, "/embeddings")
        headers = {"Content-Type": "application/json"}
        api_key = self._resolve_api_key(self.settings.embedding_api_key, self.settings.embedding_api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        result = self._post_json(
            url,
            {"model": model, "input": text},
            headers=headers,
            timeout=self.settings.embedding_timeout,
        )
        if "error" in result:
            return []
        try:
            emb = result["data"][0]["embedding"]
            return emb if isinstance(emb, list) else []
        except Exception:
            return []

    def _post_json(self, url, payload, headers=None, timeout=60):
        last_error = None
        for attempt in range(max(1, self.settings.max_retries + 1)):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code >= 400:
                    return {"error": f"HTTP {response.status_code}: {response.text[:500]}"}
                return response.json()
            except requests.Timeout as exc:
                last_error = f"请求超时: {exc}"
            except requests.RequestException as exc:
                last_error = f"网络请求异常: {exc}"
            except ValueError as exc:
                return {"error": f"响应不是合法 JSON: {exc}"}
            if attempt < self.settings.max_retries:
                time.sleep(min(2 ** attempt, 5))
        return {"error": last_error or "未知网络错误"}

    @staticmethod
    def _resolve_api_key(api_key, api_key_env):
        if api_key:
            return api_key
        if api_key_env:
            return os.getenv(api_key_env, "")
        return ""

    @staticmethod
    def _join_url(base_url, suffix):
        base = (base_url or "").rstrip("/")
        return base + suffix


_CLIENT = LLMClient()


def configure_llm(settings):
    global _CLIENT
    if isinstance(settings, LLMSettings):
        _CLIENT = LLMClient(settings)
    elif isinstance(settings, dict):
        _CLIENT = LLMClient(LLMSettings(**settings))
    else:
        raise TypeError("settings must be LLMSettings or dict")


def configure_llm_from_context(ctx):
    configure_llm(
        LLMSettings(
            provider=ctx.llm_provider,
            model=ctx.llm_model,
            base_url=ctx.llm_base_url,
            api_key_env=ctx.llm_api_key_env,
            api_key=ctx.llm_api_key,
            temperature=ctx.llm_temperature,
            timeout=ctx.llm_timeout,
            max_retries=ctx.llm_max_retries,
            embedding_provider=ctx.embedding_provider,
            embedding_model=ctx.embedding_model,
            embedding_base_url=ctx.embedding_base_url,
            embedding_api_key_env=ctx.embedding_api_key_env,
            embedding_api_key=ctx.embedding_api_key,
            embedding_timeout=ctx.embedding_timeout,
        )
    )


def get_llm_client():
    return _CLIENT


def get_embedding(text, model=None):
    try:
        return _CLIENT.embedding(text, model=model)
    except Exception:
        return []


def query_llm(prompt):
    try:
        return _CLIENT.chat(prompt)
    except Exception as exc:
        return f"网络请求异常: {exc}"


def query_ollama(prompt):
    previous = _CLIENT
    try:
        model = previous.settings.model if previous.settings.provider.lower() == "ollama" else os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
        settings = LLMSettings(
            provider="ollama",
            model=model,
            base_url=previous.settings.embedding_base_url,
            temperature=previous.settings.temperature,
            timeout=previous.settings.timeout,
            max_retries=previous.settings.max_retries,
        )
        return LLMClient(settings).chat(prompt)
    except Exception as exc:
        return f"网络请求异常: {exc}"
