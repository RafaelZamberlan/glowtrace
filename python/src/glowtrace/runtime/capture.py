"""Side-effect-free value capture with PII / secret redaction.

Rules:
* never call an arbitrary ``__repr__`` / property: objects are shown through their
  instance ``__dict__`` only (an ORM's lazy attributes are not in ``__dict__``,
  so nothing is lazily loaded);
* everything is bounded: depth, items per container, string length and a total
  budget per captured value;
* sensitive keys (password, token, cookie, cpf...) and sensitive values (JWT,
  bearer tokens, CPF/CNPJ with valid check digits, card numbers passing Luhn,
  e-mails) are redacted *before* anything leaves the process.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import enum
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

REDACTED = "[REDACTED]"

_STRONG_KEY_PARTS = (
    "password",
    "passwd",
    "senha",
    "secret",
    "token",
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "privatekey",
    "private_key",
    "credential",
    "cpf",
    "cnpj",
    "creditcard",
    "cartao",
    "cartão",
)
_EXACT_KEY_TOKENS = {
    "pwd",
    "pin",
    "cvv",
    "cvc",
    "rg",
    "otp",
    "auth",
    "session",
    "sessionid",
    "signature",
    "card",
    "jwt",
    "bearer",
}

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT = re.compile(r"[^a-z0-9]+")


def _cpf_ok(digits: str) -> bool:
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(digits[i]) * (n + 1 - i) for i in range(n))
        d = (s * 10) % 11 % 10
        if d != int(digits[n]):
            return False
    return True


def _cnpj_ok(digits: str) -> bool:
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    for w, n in ((w1, 12), (w2, 13)):
        s = sum(int(digits[i]) * w[i] for i in range(n))
        d = 0 if s % 11 < 2 else 11 - s % 11
        if d != int(digits[n]):
            return False
    return True


def _luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class CaptureConfig:
    max_depth: int = 4
    max_items: int = 25
    max_str: int = 400
    budget: int = 400  # rough number of leaf values per captured object
    redact_keys: tuple[str, ...] = ()
    allow_keys: tuple[str, ...] = ()
    redact_emails: bool = True
    redact_values: bool = True
    _extra_keys: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        self._extra_keys = {k.lower() for k in self.redact_keys}


class Capturer:
    def __init__(self, config: CaptureConfig | None = None) -> None:
        self.cfg = config or CaptureConfig()
        self._key_cache: dict[str, bool] = {}
        self._allow = {k.lower() for k in self.cfg.allow_keys}

    # -- keys ------------------------------------------------------------------
    def sensitive_key(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        hit = self._key_cache.get(key)
        if hit is not None:
            return hit
        low = key.lower()
        if low in self._allow:
            res = False
        elif low in self.cfg._extra_keys:
            res = True
        else:
            compact = low.replace("-", "").replace("_", "")
            res = any(p.replace("_", "") in compact for p in _STRONG_KEY_PARTS)
            if not res:
                tokens = set(_SPLIT.split(_CAMEL.sub("_", key).lower()))
                res = bool(tokens & _EXACT_KEY_TOKENS)
        if len(self._key_cache) < 10000:
            self._key_cache[key] = res
        return res

    # -- strings -----------------------------------------------------------------
    def scrub_text(self, text: str) -> str:
        if not self.cfg.redact_values or not text:
            return text
        text = _JWT.sub("[JWT]", text)
        text = _BEARER.sub(lambda m: m.group(1) + " " + REDACTED, text)

        def cnpj(m: re.Match) -> str:
            d = re.sub(r"\D", "", m.group(0))
            return "[CNPJ]" if _cnpj_ok(d) else m.group(0)

        def cpf(m: re.Match) -> str:
            d = re.sub(r"\D", "", m.group(0))
            return "[CPF]" if _cpf_ok(d) else m.group(0)

        def card(m: re.Match) -> str:
            d = re.sub(r"\D", "", m.group(0))
            return "[CARD]" if _luhn_ok(d) else m.group(0)

        text = _CNPJ.sub(cnpj, text)
        text = _CPF.sub(cpf, text)
        text = _CARD.sub(card, text)
        if self.cfg.redact_emails:
            text = _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
        return text

    def _str(self, s: str) -> str:
        limit = self.cfg.max_str
        if len(s) > limit:
            s = s[:limit] + f"…(+{len(s) - limit})"
        return self.scrub_text(s)

    # -- values ------------------------------------------------------------------
    def capture(self, value: Any) -> Any:
        budget = [self.cfg.budget]
        try:
            return self._cap(value, 0, budget)
        except Exception as exc:  # never break the user's request
            return f"<capture error: {type(exc).__name__}>"

    def capture_mapping(self, mapping: dict, names: Iterable[str] | None = None) -> dict:
        out = {}
        budget = [self.cfg.budget]
        keys = names if names is not None else list(mapping.keys())
        for k in keys:
            if k not in mapping:
                continue
            if self.sensitive_key(k):
                out[k] = REDACTED
                continue
            try:
                out[k] = self._cap(mapping[k], 0, budget)
            except Exception as exc:
                out[k] = f"<capture error: {type(exc).__name__}>"
        return out

    def _cap(self, v: Any, depth: int, budget: list[int]) -> Any:
        budget[0] -= 1
        if budget[0] < 0:
            return "…"
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, int):
            return v if abs(v) < 2**53 else str(v)
        if isinstance(v, float):
            return v if v == v and v not in (float("inf"), float("-inf")) else str(v)
        if isinstance(v, str):
            return self._str(v)
        if isinstance(v, (bytes, bytearray, memoryview)):
            return f"<bytes {len(v)}>"
        if isinstance(v, enum.Enum):
            return f"{type(v).__name__}.{v.name}"
        if isinstance(v, (_dt.datetime, _dt.date, _dt.time, _dt.timedelta, decimal.Decimal, uuid.UUID)):
            return str(v)
        if depth >= self.cfg.max_depth:
            return f"<{type(v).__name__}>"
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            for i, (k, val) in enumerate(v.items()):
                if i >= self.cfg.max_items:
                    out["…"] = f"+{len(v) - i} itens"
                    break
                ks = k if isinstance(k, str) else str(k) if isinstance(k, (int, float, bool, enum.Enum)) else f"<{type(k).__name__}>"
                out[ks] = REDACTED if self.sensitive_key(ks) else self._cap(val, depth + 1, budget)
            return out
        if isinstance(v, (list, tuple, set, frozenset)):
            items = list(v)[: self.cfg.max_items] if not isinstance(v, (list, tuple)) else v[: self.cfg.max_items]
            res = [self._cap(x, depth + 1, budget) for x in items]
            if len(v) > self.cfg.max_items:
                res.append(f"…(+{len(v) - self.cfg.max_items})")
            return res
        if isinstance(v, BaseException):
            return {"__type__": type(v).__name__, "message": self._str(_safe_str(v))}
        return self._object(v, depth, budget)

    def _object(self, v: Any, depth: int, budget: list[int]) -> Any:
        t = type(v)
        mod = getattr(t, "__module__", "") or ""
        name = t.__name__
        root = mod.split(".")[0]
        # well-known heavy types: summarize without touching data
        if root in ("pandas", "geopandas", "numpy", "polars"):
            try:
                shape = getattr(v, "shape", None)
                return f"<{name} shape={tuple(shape) if shape is not None else '?'}>"
            except Exception:
                return f"<{name}>"
        if root in _FRAMEWORK_ROOTS:
            # framework objects are noise (and may hold the whole app): summarize
            if name.endswith("Request") or name == "WebSocket":
                try:
                    scope = object.__getattribute__(v, "scope")
                    return f"<{name} {scope.get('method', '')} {scope.get('path', '')}>"
                except Exception:
                    return f"<{name}>"
            if name.endswith("Response"):
                try:
                    return f"<{name} status={object.__getattribute__(v, 'status_code')}>"
                except Exception:
                    return f"<{name}>"
            return f"<{name}>"
        if hasattr(v, "__await__") or hasattr(v, "__anext__") or hasattr(v, "gi_frame"):
            return f"<{name}>"
        d = None
        try:
            d = object.__getattribute__(v, "__dict__")
        except Exception:
            d = None
        if isinstance(d, dict):
            out: dict[str, Any] = {"__type__": name}
            count = 0
            for k, val in d.items():
                if not isinstance(k, str) or k.startswith("_"):
                    continue
                if count >= self.cfg.max_items:
                    out["…"] = "…"
                    break
                out[k] = REDACTED if self.sensitive_key(k) else self._cap(val, depth + 1, budget)
                count += 1
            # pydantic v2 keeps fields in __dict__; slots-only objects fall through
            if count or len(out) > 1:
                return out
            return f"<{mod + '.' if mod and mod != 'builtins' else ''}{name}>"
        slots = getattr(t, "__slots__", None)
        if slots and isinstance(slots, (tuple, list)):
            out = {"__type__": name}
            for k in slots[: self.cfg.max_items]:
                if isinstance(k, str) and not k.startswith("_"):
                    try:
                        val = object.__getattribute__(v, k)
                    except Exception:
                        continue
                    out[k] = REDACTED if self.sensitive_key(k) else self._cap(val, depth + 1, budget)
            return out
        return f"<{mod + '.' if mod and mod != 'builtins' else ''}{name}>"


_FRAMEWORK_ROOTS = {
    "starlette",
    "fastapi",
    "uvicorn",
    "anyio",
    "asyncio",
    "sqlalchemy",
    "pymongo",
    "motor",
    "redis",
    "httpx",
    "requests",
    "aiohttp",
    "logging",
    "threading",
    "concurrent",
}


def _safe_str(e: BaseException) -> str:
    try:
        return str(e)
    except Exception:
        return type(e).__name__


_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
    "x-csrf-token",
    "x-glowtrace-token",
}


def scrub_headers(headers: Iterable[tuple[bytes, bytes]], cap: Capturer) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers:
        key = k.decode("latin-1").lower()
        if key in _SENSITIVE_HEADERS or cap.sensitive_key(key):
            out[key] = REDACTED
        else:
            val = v.decode("latin-1")
            out[key] = cap.scrub_text(val[:300])
    return out
