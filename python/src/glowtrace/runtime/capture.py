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

import collections
import collections.abc
import datetime as _dt
import decimal
import enum
import fractions
import ipaddress
import json
import pathlib
import re
import types
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

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
    max_depth: int = 8  # nesting levels opened; `budget` is what bounds the size
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
        budget: list = [self.cfg.budget, set()]  # [values left, ids of the containers being opened]
        try:
            return self._cap(value, 0, budget)
        except Exception as exc:  # never break the user's request
            return f"<capture error: {type(exc).__name__}>"

    def capture_mapping(self, mapping: dict, names: Iterable[str] | None = None) -> dict:
        out = {}
        budget: list = [self.cfg.budget, set()]
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

    def _cap(self, v: Any, depth: int, budget: list) -> Any:
        budget[0] -= 1
        if budget[0] < 0:
            return "…"
        if v is None or isinstance(v, bool):
            return v
        if isinstance(v, enum.Enum):  # before int/str: IntEnum / StrEnum
            return f"{type(v).__name__}.{v.name}"
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
        if isinstance(v, _STR_VALUES) or _str_value(v):  # value types whose str() is the value
            return self._str(str(v))
        if depth >= self.cfg.max_depth:
            return f"<{type(v).__name__}>"
        path = budget[1] if len(budget) > 1 else None
        if path is None:
            return self._nested(v, depth, budget)
        vid = id(v)
        if vid in path:  # object graph that points back to itself (ORM back-references...)
            return f"<ciclo {type(v).__name__}>"
        path.add(vid)
        try:
            return self._nested(v, depth, budget)
        finally:
            path.discard(vid)

    def _nested(self, v: Any, depth: int, budget: list) -> Any:
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            for i, (k, val) in enumerate(v.items()):
                if i >= self.cfg.max_items:
                    out["…"] = f"+{len(v) - i} itens"
                    break
                ks = k if isinstance(k, str) else str(k) if isinstance(k, (int, float, bool, enum.Enum)) else f"<{type(k).__name__}>"
                out[ks] = REDACTED if self.sensitive_key(ks) else self._cap(val, depth + 1, budget)
            return out
        mapping = _readable_mapping(v)
        if mapping is not None:
            return self._nested(mapping, depth, budget)
        if isinstance(v, tuple) and hasattr(type(v), "_fields"):  # NamedTuple: keep the field names
            return self._nested(dict(zip(type(v)._fields, v)), depth, budget)
        if isinstance(v, (list, tuple, set, frozenset, collections.deque)):
            items = list(v)[: self.cfg.max_items] if not isinstance(v, (list, tuple)) else v[: self.cfg.max_items]
            res = [self._cap(x, depth + 1, budget) for x in items]
            if len(v) > self.cfg.max_items:
                res.append(f"…(+{len(v) - self.cfg.max_items})")
            return res
        if isinstance(v, BaseException):
            return {"__type__": type(v).__name__, "message": self._str(_safe_str(v))}
        return self._object(v, depth, budget)

    def _object(self, v: Any, depth: int, budget: list) -> Any:
        t = type(v)
        mod = getattr(t, "__module__", "") or ""
        name = t.__name__
        root = mod.split(".")[0]
        # data libraries: a bounded preview (never the whole thing)
        if root in ("pandas", "geopandas", "numpy", "polars"):
            try:
                return self._tabular(v, root, name, depth, budget)
            except Exception:
                return f"<{name}>"
        if root in _FRAMEWORK_ROOTS:
            # framework objects are noise (and may hold the whole app): summarize,
            # except the ones that are plain data (responses, uploads, rows)
            try:
                data = self._framework_data(v, root, name, depth, budget)
            except Exception:
                data = None
            if data is not None:
                return data
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
            return f"<{name}: não lido (ler consumiria)>"
        if isinstance(v, (types.FunctionType, types.BuiltinFunctionType, types.MethodType, type)):
            return f"<{name} {getattr(v, '__qualname__', '')}>"
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

    # -- data that lives inside framework / data-library objects -----------------
    def _framework_data(self, v: Any, root: str, name: str, depth: int, budget: list) -> Any:
        """Framework objects that are plain, already-in-memory data. Attributes are read
        with object.__getattribute__ (no properties, no I/O); None = not one of them."""
        get = object.__getattribute__
        if name.endswith("Response") and root in ("starlette", "fastapi", "httpx", "requests"):
            out: dict[str, Any] = {"__type__": name}
            try:
                out["status_code"] = get(v, "status_code")
            except Exception:
                pass
            media = None
            try:
                media = get(v, "media_type")  # starlette
            except Exception:
                try:
                    media = get(v, "headers").get("content-type")  # httpx / requests (in-memory mapping)
                except Exception:
                    media = None
            if media:
                out["media_type"] = str(media)
            body = None
            for attr in ("body", "_content"):  # starlette renders `body` up front; httpx/requests keep `_content` once read
                try:
                    body = get(v, attr)
                    break
                except Exception:
                    continue
            if isinstance(body, (bytes, bytearray)):
                out["body"] = self._body(bytes(body), str(media or ""), depth, budget)
            elif name in ("StreamingResponse", "FileResponse", "EventSourceResponse"):
                out["body"] = "<stream: não lido>"
            else:
                out["body"] = "<corpo ainda não lido>"
            try:
                loc = dict(get(v, "headers")).get("location")
                if loc:
                    out["location"] = self._str(str(loc))
            except Exception:
                pass
            return out
        if name == "UploadFile":
            out = {"__type__": name}
            for attr in ("filename", "size"):
                try:
                    out[attr] = self._cap(get(v, attr), depth + 1, budget)
                except Exception:
                    pass
            try:
                out["content_type"] = get(v, "headers").get("content-type")
            except Exception:
                pass
            return out
        if name == "URL" and root == "starlette":
            return self._str(str(v))
        if name == "BackgroundTasks":
            try:
                tasks = get(v, "tasks")
                return {"__type__": name, "tarefas": [getattr(t.func, "__qualname__", "?") for t in tasks][: self.cfg.max_items]}
            except Exception:
                return None
        if root == "sqlalchemy" and name in ("Row", "LegacyRow"):
            try:
                return self._nested(dict(v._mapping), depth, budget)  # values already fetched
            except Exception:
                return None
        return None

    def _body(self, raw: bytes, media: str, depth: int, budget: list) -> Any:
        if not raw:
            return ""
        if "json" in media or raw[:1] in (b"{", b"["):
            try:
                return self._cap(json.loads(raw[:1_000_000]), depth + 1, budget)
            except Exception:
                pass
        if any(t in media for t in ("text", "json", "xml", "html", "x-www-form-urlencoded")) or not media:
            return self._str(raw.decode("utf-8", "replace"))
        return f"<bytes {len(raw)}>"

    def _tabular(self, v: Any, root: str, name: str, depth: int, budget: list) -> Any:
        """numpy / pandas / polars: shape and a small preview, never the whole data."""
        n = self.cfg.max_items
        shape = getattr(v, "shape", None)
        if root == "numpy":
            if shape == () and hasattr(v, "item"):  # numpy scalar (int64, float32...)
                return self._cap(v.item(), depth, budget)
            flat = v.reshape(-1)[:n].tolist() if hasattr(v, "reshape") else None
            out = {"__type__": name, "shape": list(shape or ()), "dtype": str(getattr(v, "dtype", "?"))}
            if flat is not None:
                if getattr(v, "ndim", 1) == 1 or (shape and len(shape) == 2 and shape[0] * shape[1] <= n):
                    out["valores"] = self._cap(v[:n].tolist() if getattr(v, "ndim", 1) == 1 else v.tolist(), depth + 1, budget)
                else:
                    out["primeiros"] = self._cap(flat, depth + 1, budget)
            return out
        if root in ("pandas", "geopandas") and name in ("DataFrame", "GeoDataFrame"):
            head = v.head(5)
            return {
                "__type__": name,
                "shape": list(shape),
                "colunas": [str(c) for c in list(v.columns)[:n]],
                "primeiras_linhas": self._cap(head.iloc[:, :n].to_dict("records"), depth + 1, budget),
            }
        if root in ("pandas", "geopandas") and name in ("Series", "GeoSeries"):
            return {
                "__type__": name,
                "name": self._cap(getattr(v, "name", None), depth + 1, budget),
                "len": int(shape[0]) if shape else None,
                "primeiros": self._cap(v.head(n).tolist(), depth + 1, budget),
            }
        if root == "pandas" and hasattr(v, "isoformat"):  # Timestamp / Timedelta-like
            return self._str(str(v))
        if root == "polars" and name == "DataFrame":
            return {"__type__": name, "shape": list(shape), "colunas": [str(c) for c in list(v.columns)[:n]]}
        return f"<{name} shape={tuple(shape) if shape is not None else '?'}>"



# value types whose str() is exactly the value (pure, no I/O)
_STR_VALUES = (
    complex,
    fractions.Fraction,
    pathlib.PurePath,
    range,
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    ipaddress.IPv4Network,
    ipaddress.IPv6Network,
    ipaddress.IPv4Interface,
    ipaddress.IPv6Interface,
)


def _str_value(v: Any) -> bool:
    t = type(v)
    return t.__name__ == "ObjectId" and (getattr(t, "__module__", "") or "").startswith("bson")


# Mappings that only hold data already in memory (multi-value ones keep every value)
_MAPPING_ROOTS = {"starlette", "fastapi", "multidict", "werkzeug", "requests", "httpx", "sqlalchemy", "collections", "types", "bson"}


def _readable_mapping(v: Any) -> Optional[dict]:
    if isinstance(v, dict) or not isinstance(v, collections.abc.Mapping):
        return None
    root = (getattr(type(v), "__module__", "") or "").split(".")[0]
    if root not in _MAPPING_ROOTS and not isinstance(v, (types.MappingProxyType, collections.ChainMap)):
        return None
    try:
        pairs = v.multi_items() if hasattr(v, "multi_items") else list(v.items())
    except Exception:
        return None
    out: dict = {}
    multi: set = set()
    for k, val in pairs:
        if k not in out:
            out[k] = val
        elif k in multi:
            out[k].append(val)
        else:
            out[k] = [out[k], val]
            multi.add(k)
    return out


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
