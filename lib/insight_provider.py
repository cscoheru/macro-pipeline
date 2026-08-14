"""Structured macro insight generation via a pluggable LLM provider.

Two backends, selected by INSIGHT_PROVIDER in config/insight.env:
  * "anthropic" (default) — Anthropic Messages API with json_schema output.
  * "deepseek"            — OpenAI-compatible /chat/completions (DeepSeek) with
                            json_object output.

Both return a parsed dict; the hard validator (insight_validate) is API-agnostic,
so DeepSeek's weaker server-side JSON enforcement is harmless — any schema or
fact deviation lands in needs_review. Secrets are read only from config/insight.env
(mode 600) and never logged, echoed, or persisted in the ledger/artifact/vault.
"""
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass

import requests

import insight_context
import paths


class ProviderError(RuntimeError):
    def __init__(self, message, *, retryable=False, error_class="provider_error"):
        super().__init__(message)
        self.retryable = retryable
        self.error_class = error_class


class ConfigurationError(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    provider: str = "anthropic"
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = "claude-fable-5"
    timeout_seconds: int = 90
    max_tokens: int = 6000
    max_retries: int = 2
    max_input_chars: int = 80000


def _parse_env_file(path):
    if not os.path.exists(path):
        return {}
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise ConfigurationError(
            f"insight env permissions must be 600, got {oct(mode)}",
            error_class="insecure_config",
        )
    values = {}
    with open(path, encoding="utf-8") as handle:
        for number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ConfigurationError(
                    f"invalid insight env line {number}", error_class="invalid_config"
                )
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"").strip("'")
    return values


def _integer(values, name, default, *, minimum=1):
    raw = values.get(name, str(default))
    try:
        parsed = int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{name} must be an integer", error_class="invalid_config"
        ) from exc
    if parsed < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}", error_class="invalid_config"
        )
    return parsed


def load_config(env_path=None, environ=None):
    # File wins over ambient environment: a stray ANTHROPIC_API_KEY (or a
    # redirected base_url) left in the launching shell must never silently
    # override the permission-checked insight.env. Ambient env only fills
    # keys the file does not set.
    file_values = _parse_env_file(env_path or paths.INSIGHT_ENV)
    values = {**dict(os.environ if environ is None else environ), **file_values}
    provider = values.get("INSIGHT_PROVIDER", "anthropic").strip().lower()
    common = {
        "timeout_seconds": _integer(values, "INSIGHT_TIMEOUT_SECONDS", 90),
        "max_tokens": _integer(values, "INSIGHT_MAX_TOKENS", 6000),
        "max_retries": _integer(values, "INSIGHT_MAX_RETRIES", 2, minimum=0),
        "max_input_chars": _integer(values, "INSIGHT_MAX_INPUT_CHARS", 80000),
    }
    if provider == "deepseek":
        api_key = values.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "DEEPSEEK_API_KEY is not configured", error_class="missing_api_key"
            )
        return ProviderConfig(
            provider="deepseek",
            api_key=api_key,
            base_url=values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=values.get("INSIGHT_MODEL", "deepseek-chat"),
            **common,
        )
    api_key = values.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError(
            "ANTHROPIC_API_KEY is not configured", error_class="missing_api_key"
        )
    return ProviderConfig(
        provider="anthropic",
        api_key=api_key,
        base_url=values.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
        model=values.get("INSIGHT_MODEL", "claude-fable-5"),
        **common,
    )


def load_prompt_and_schema(prompt_path=None, schema_path=None):
    with open(prompt_path or paths.INSIGHT_PROMPT, encoding="utf-8") as handle:
        prompt = handle.read()
    with open(schema_path or paths.INSIGHT_SCHEMA, encoding="utf-8") as handle:
        schema = json.load(handle)
    version = insight_context.content_sha256({"prompt": prompt, "schema": schema})[:16]
    return prompt, schema, version


def build_provider(config=None, *, post=None, sleep=None):
    """Construct the configured provider; injectable post/sleep for tests."""
    cfg = config or load_config()
    if cfg.provider == "deepseek":
        return DeepSeekInsightProvider(cfg, post=post, sleep=sleep)
    return AnthropicInsightProvider(cfg, post=post, sleep=sleep)


def _retry_delay(response, attempt):
    if response is not None:
        raw = response.headers.get("retry-after")
        try:
            return min(max(float(raw), 0.0), 60.0)
        except (TypeError, ValueError):
            pass
    return min(2 ** attempt, 30)


def _request_with_retry(url, headers, payload, config, post, sleep):
    """POST JSON with retry on transient errors; return parsed body dict.

    429/5xx are retryable; other 4xx are fatal; network errors retry then fail.
    The API key is sent only in headers — never in the URL, body, or logs.
    """
    for attempt in range(config.max_retries + 1):
        try:
            response = post(
                url, headers=headers, json=payload, timeout=config.timeout_seconds,
            )
        except requests.RequestException as exc:
            if attempt < config.max_retries:
                sleep(_retry_delay(None, attempt))
                continue
            raise ProviderError(
                "provider network request failed", retryable=True,
                error_class="network_error",
            ) from exc
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < config.max_retries:
                sleep(_retry_delay(response, attempt))
                continue
            raise ProviderError(
                f"provider unavailable (HTTP {response.status_code})",
                retryable=True, error_class=f"http_{response.status_code}",
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"provider rejected request (HTTP {response.status_code})",
                error_class=f"http_{response.status_code}",
            )
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError(
                "provider returned non-JSON response", error_class="invalid_response"
            ) from exc
    raise ProviderError("provider retry loop exhausted", retryable=True)


def _persist_raw_failure(text):
    """Best-effort: keep unparsable model output for diagnosis.

    Without this, an invalid_json failure left no trace of what the model
    actually returned (e.g. a truncation vs. prose answer is indistinguishable).
    Content-addressed under failed_responses/, mode 600, never raises.
    """
    try:
        directory = os.path.join(paths.INSIGHT_DIR, "failed_responses")
        os.makedirs(directory, mode=0o700, exist_ok=True)
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        target = os.path.join(directory, f"{digest}.txt")
        if not os.path.exists(target):
            tmp = f"{target}.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(text or "")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        return target
    except OSError:
        return None


def _coerce_json_object(text):
    """Parse a JSON object from model text, tolerating stray code fences."""
    text = (text or "").strip()
    if not text:
        raise ProviderError("provider returned empty content", error_class="invalid_response")
    if text.startswith("```"):
        fence_end = text.find("\n")
        if fence_end != -1 and len(text[:fence_end].strip(" `")) < 16:
            text = text[fence_end + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        path = _persist_raw_failure(text)
        suffix = f" (raw output kept at {path})" if path else ""
        raise ProviderError(
            f"provider returned invalid JSON{suffix}", error_class="invalid_json"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderError("provider JSON must be an object", error_class="invalid_json")
    return parsed


def _extract_anthropic_json(response_body):
    content = response_body.get("content")
    if not isinstance(content, list):
        raise ProviderError("provider response has no content", error_class="invalid_response")
    text = "".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    return _coerce_json_object(text)


def _salvage_json_from_reasoning(reasoning):
    """Extract the last balanced {...} block from reasoning_content.

    deepseek-reasoner occasionally finishes (finish_reason=stop) with the
    answer draft left in reasoning_content and an empty content field.
    Anything salvaged still goes through _coerce_json_object and the hard
    validator, so this widens recovery without weakening any gate.
    """
    text = reasoning or ""
    for start in range(text.rfind("{"), -1, -1):
        if text[start] != "{":
            continue
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return json.dumps(parsed, ensure_ascii=False)
                    break
        # no balanced object at this '{' — try the previous one
    return None


def _extract_openai_json(response_body):
    choices = response_body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("provider response has no choices", error_class="invalid_response")
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if not (content or "").strip():
        salvaged = _salvage_json_from_reasoning(message.get("reasoning_content"))
        if salvaged:
            return _coerce_json_object(salvaged)
        # Distinguish "reasoning burned the whole budget" (finish_reason=length,
        # raise max_tokens or simplify the fact pack) from a genuinely empty answer.
        finish = choice.get("finish_reason")
        raise ProviderError(
            f"provider returned empty content (finish_reason={finish})",
            error_class="invalid_response",
        )
    return _coerce_json_object(content)


def _fact_pack_text(fact_pack, config):
    user_text = insight_context.canonical_json(fact_pack)
    if len(user_text) > config.max_input_chars:
        raise ProviderError(
            "fact pack exceeds configured input limit", error_class="input_too_large"
        )
    return user_text


class AnthropicInsightProvider:
    def __init__(self, config, *, post=None, sleep=None):
        self.config = config
        self._post = post or requests.post
        self._sleep = sleep or time.sleep

    def _payload(self, fact_pack, prompt, schema):
        return {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": prompt,
            "messages": [{"role": "user", "content": _fact_pack_text(fact_pack, self.config)}],
            "output_config": {
                "format": {"type": "json_schema", "schema": schema}
            },
        }

    def generate(self, fact_pack, *, prompt=None, schema=None):
        if prompt is None or schema is None:
            loaded_prompt, loaded_schema, _ = load_prompt_and_schema()
            prompt = prompt or loaded_prompt
            schema = schema or loaded_schema
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = _request_with_retry(
            f"{self.config.base_url}/v1/messages", headers,
            self._payload(fact_pack, prompt, schema),
            self.config, self._post, self._sleep,
        )
        return _extract_anthropic_json(body)


class DeepSeekInsightProvider:
    """OpenAI-compatible provider (DeepSeek). Returns parsed JSON via json_object mode."""

    def __init__(self, config, *, post=None, sleep=None):
        self.config = config
        self._post = post or requests.post
        self._sleep = sleep or time.sleep

    def _payload(self, fact_pack, prompt, schema):
        system = (
            f"{prompt}\n\n"
            "只输出一个 JSON 对象，不要任何解释、Markdown 或代码围栏。"
            f"JSON 必须严格匹配此 json schema：\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": _fact_pack_text(fact_pack, self.config)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }

    def generate(self, fact_pack, *, prompt=None, schema=None):
        if prompt is None or schema is None:
            loaded_prompt, loaded_schema, _ = load_prompt_and_schema()
            prompt = prompt or loaded_prompt
            schema = schema or loaded_schema
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "content-type": "application/json",
        }
        body = _request_with_retry(
            f"{self.config.base_url}/chat/completions", headers,
            self._payload(fact_pack, prompt, schema),
            self.config, self._post, self._sleep,
        )
        return _extract_openai_json(body)
