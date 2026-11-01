"""AI Orchestrator: provider interface, cost-aware routing, daily budget, usage ledger.

Rules (docs/EXECUTION_SECURITY.md applies to anything that touches the machine; this module only
talks to language models):
- Local providers are tried first (cost 0). Cloud providers are used as fallback or on request.
- Cloud calls stop when today's spend reaches the daily budget (default 1.00 USD).
- API keys come from environment variables only and never appear in logs, errors or the database.
- The usage ledger stores token counts and cost, never prompt or answer text.
- A local provider must point at a loopback address; a cloud provider must use https.
"""

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Dict, List, Mapping, Optional
from urllib.parse import urlsplit

from .storage import Storage, StorageError

MAX_PROMPT_CHARS = 100_000
MAX_OUTPUT_TOKENS = 8192
LOCAL, CLOUD = "local", "cloud"


class ProviderError(Exception):
    """A provider failed; the router may fall back to the next one."""


class OrchestratorError(StorageError):
    pass


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


@dataclass
class Provider:
    name: str
    kind: str = LOCAL
    model: str = "unknown"
    price_in_per_1k: float = 0.0
    price_out_per_1k: float = 0.0

    def complete(self, prompt: str, system: Optional[str], max_tokens: int) -> Completion:
        raise NotImplementedError

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return round(tokens_in / 1000 * self.price_in_per_1k + tokens_out / 1000 * self.price_out_per_1k, 6)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class MockProvider(Provider):
    """Deterministic provider for tests and offline demos. Optionally fails on demand."""
    name: str = "mock"
    model: str = "mock-1"
    fail: bool = False
    calls: int = field(default=0, repr=False)

    def complete(self, prompt, system, max_tokens):
        self.calls += 1
        if self.fail:
            raise ProviderError("mock provider failure")
        text = f"[mock] {prompt[:200]}"
        return Completion(text, estimate_tokens((system or "") + prompt), estimate_tokens(text), self.model)


class OpenAICompatProvider(Provider):
    """Chat-completions endpoint (Ollama, LM Studio, llama.cpp server, or a hosted API)."""

    def __init__(self, name, kind, base_url, model, api_key=None, price_in_per_1k=0.0,
                 price_out_per_1k=0.0, timeout=120):
        super().__init__(name=name, kind=kind, model=model, price_in_per_1k=price_in_per_1k,
                         price_out_per_1k=price_out_per_1k)
        self.base_url = validate_base_url(base_url, kind)
        self._api_key = api_key  # never exposed through repr(), errors or the ledger
        self.timeout = timeout

    def __repr__(self):
        return f"OpenAICompatProvider(name={self.name!r}, kind={self.kind!r}, model={self.model!r})"

    def complete(self, prompt, system, max_tokens):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = json.dumps({"model": self.model, "messages": messages, "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if self._api_key:
            req.add_header("Authorization", "Bearer " + self._api_key)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if self.kind == LOCAL else None))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read(5_000_000))
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage") or {}
            return Completion(text, int(usage.get("prompt_tokens") or estimate_tokens(prompt)),
                              int(usage.get("completion_tokens") or estimate_tokens(text)), self.model)
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"{self.name}: HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"{self.name}: unreachable ({type(exc).__name__})")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name}: malformed response")


def validate_base_url(url: str, kind: str) -> str:
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if kind == LOCAL:
        if parts.scheme not in ("http", "https"):
            raise ValueError("Local provider URL must be http(s)")
        loopback = host == "localhost"
        try:
            loopback = loopback or ip_address(host).is_loopback
        except ValueError:
            pass
        if not loopback:
            raise ValueError("Local provider must point at localhost / a loopback address")
    elif parts.scheme != "https" or not host:
        raise ValueError("Cloud provider URL must use https")
    return url.rstrip("/")


def build_providers(env: Mapping[str, str]) -> List[Provider]:
    """Providers from environment. Nothing is enabled unless configured (mock is opt-in)."""
    providers: List[Provider] = []
    if env.get("WACC_ENABLE_MOCK") == "1":
        providers.append(MockProvider())
    if env.get("WACC_LOCAL_LLM_URL"):
        providers.append(OpenAICompatProvider("local-llm", LOCAL, env["WACC_LOCAL_LLM_URL"],
                                              env.get("WACC_LOCAL_LLM_MODEL", "local-model")))
    if env.get("WACC_CLOUD_LLM_URL"):
        key = env.get("WACC_CLOUD_LLM_KEY")
        if not key:
            raise ValueError("WACC_CLOUD_LLM_KEY is required when WACC_CLOUD_LLM_URL is set")
        providers.append(OpenAICompatProvider(
            "cloud-llm", CLOUD, env["WACC_CLOUD_LLM_URL"], env.get("WACC_CLOUD_LLM_MODEL", "cloud-model"),
            api_key=key, price_in_per_1k=float(env.get("WACC_CLOUD_PRICE_IN_PER_1K", "0.003")),
            price_out_per_1k=float(env.get("WACC_CLOUD_PRICE_OUT_PER_1K", "0.015"))))
    return providers


_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|api[_-]?key\s*[=:]\s*\S+)", re.I)


def scrub(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text or "")[:300]


class Orchestrator:
    def __init__(self, storage: Storage, providers: Optional[List[Provider]] = None):
        self.storage = storage
        self.providers: Dict[str, Provider] = {}
        for p in providers or []:
            self.add_provider(p)

    def add_provider(self, provider: Provider) -> None:
        if provider.kind not in (LOCAL, CLOUD):
            raise ValueError("Provider kind must be 'local' or 'cloud'")
        self.providers[provider.name] = provider

    # ----------------------------------------------------------------- budget
    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_budget(self) -> float:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT value FROM engine_flags WHERE key='daily_budget_usd'").fetchone()
            return float(r["value"]) if r else 1.0
        finally:
            conn.close()

    def set_budget(self, usd: float) -> float:
        if not isinstance(usd, (int, float)) or usd < 0 or usd > 1000:
            raise OrchestratorError("BAD_BUDGET", "Budget must be between 0 and 1000 USD")
        with self.storage.tx() as conn:
            conn.execute("INSERT INTO engine_flags(key, value) VALUES ('daily_budget_usd', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"{float(usd):.2f}",))
        return float(usd)

    def spent_today(self) -> float:
        conn = self.storage._connect()
        try:
            r = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) s FROM ai_usage WHERE day=?", (self._today(),)).fetchone()
            return round(r["s"], 6)
        finally:
            conn.close()

    def usage_summary(self) -> dict:
        conn = self.storage._connect()
        try:
            rows = conn.execute(
                "SELECT provider, COUNT(*) calls, SUM(ok) ok_calls, SUM(tokens_in) tin, SUM(tokens_out) tout, "
                "SUM(cost_usd) cost FROM ai_usage WHERE day=? GROUP BY provider", (self._today(),)).fetchall()
            return {"day": self._today(), "budget_usd": self.get_budget(), "spent_usd": self.spent_today(),
                    "providers": [dict(r) for r in rows]}
        finally:
            conn.close()

    def _record(self, provider: Provider, tin: int, tout: int, cost: float, ok: bool, error: Optional[str] = None):
        now = datetime.now(timezone.utc)
        with self.storage.tx() as conn:
            conn.execute(
                "INSERT INTO ai_usage(ts, day, provider, model, tokens_in, tokens_out, cost_usd, ok, error) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), now.strftime("%Y-%m-%d"), provider.name, provider.model,
                 tin, tout, cost, 1 if ok else 0, scrub(error) if error else None))

    # ---------------------------------------------------------------- routing
    def list_providers(self) -> List[dict]:
        return [{"name": p.name, "kind": p.kind, "model": p.model,
                 "price_in_per_1k": p.price_in_per_1k, "price_out_per_1k": p.price_out_per_1k}
                for p in self.providers.values()]

    def _order(self, prefer: str, only: Optional[str]) -> List[Provider]:
        if only:
            if only not in self.providers:
                raise OrchestratorError("NOT_FOUND", f"Unknown provider {only!r}")
            return [self.providers[only]]
        if prefer not in ("local", "cloud", "auto"):
            raise OrchestratorError("BAD_PREFERENCE", "prefer must be local, cloud or auto")
        locals_ = [p for p in self.providers.values() if p.kind == LOCAL]
        clouds = [p for p in self.providers.values() if p.kind == CLOUD]
        return clouds + locals_ if prefer == "cloud" else locals_ + clouds

    def complete(self, prompt: str, system: Optional[str] = None, prefer: str = "auto",
                 provider: Optional[str] = None, max_tokens: int = 1024) -> dict:
        if not (prompt or "").strip():
            raise OrchestratorError("BAD_PROMPT", "Prompt is empty")
        if len(prompt) + len(system or "") > MAX_PROMPT_CHARS:
            raise OrchestratorError("PROMPT_TOO_LARGE", f"Prompt exceeds {MAX_PROMPT_CHARS} characters")
        if not 1 <= int(max_tokens) <= MAX_OUTPUT_TOKENS:
            raise OrchestratorError("BAD_MAX_TOKENS", f"max_tokens must be 1-{MAX_OUTPUT_TOKENS}")
        candidates = self._order(prefer, provider)
        if not candidates:
            raise OrchestratorError("NO_PROVIDER", "No AI provider is configured")
        budget_blocked, errors = False, []
        for p in candidates:
            if p.kind == CLOUD:
                projected = p.cost(estimate_tokens((system or "") + prompt), int(max_tokens))
                if self.spent_today() + projected > self.get_budget():
                    budget_blocked = True
                    continue
            try:
                out = p.complete(prompt, system, int(max_tokens))
            except ProviderError as exc:
                self._record(p, 0, 0, 0.0, False, str(exc))
                errors.append(str(exc))
                continue
            cost = p.cost(out.tokens_in, out.tokens_out)
            self._record(p, out.tokens_in, out.tokens_out, cost, True)
            return {"text": out.text, "provider": p.name, "kind": p.kind, "model": out.model,
                    "tokens_in": out.tokens_in, "tokens_out": out.tokens_out, "cost_usd": cost,
                    "fallbacks": len(errors)}
        if budget_blocked and not errors:
            raise OrchestratorError("BUDGET_EXCEEDED", "Daily AI budget would be exceeded; no free provider available")
        raise OrchestratorError("ALL_FAILED", "; ".join(errors) or "No provider could serve the request")
