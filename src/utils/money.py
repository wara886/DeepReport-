"""Money and currency helpers for report artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Optional


UNKNOWN_CURRENCY = "unknown"
KNOWN_CURRENCIES = {"USD", "CNY", "HKD", "JPY", "EUR", "GBP", "TWD", "KRW", "SGD", "CAD", "AUD"}


@dataclass(frozen=True)
class MoneyValue:
    amount: float
    currency: str
    scale: str = "unit"
    source_currency: str = ""
    display_currency: str = ""
    fx_rate: Optional[float] = None
    fx_date: Optional[str] = None
    source_id: str = ""
    confidence: str = "unknown"
    inferred_from: str = ""

    def __post_init__(self) -> None:
        normalized = normalize_currency_code(self.currency)
        object.__setattr__(self, "currency", normalized)
        if normalized == UNKNOWN_CURRENCY:
            object.__setattr__(self, "confidence", "unknown")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CurrencyMetadata:
    statement_currency: str = UNKNOWN_CURRENCY
    trading_currency: str = UNKNOWN_CURRENCY
    display_currency: str = UNKNOWN_CURRENCY
    currency_basis: str = "unknown"
    confidence: str = "unknown"
    inferred_from: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_currency_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return UNKNOWN_CURRENCY
    aliases = {
        "RMB": "CNY",
        "CNH": "CNY",
        "YUAN": "CNY",
        "HK$": "HKD",
        "US$": "USD",
        "$": "USD",
    }
    text = aliases.get(text, text)
    return text if text in KNOWN_CURRENCIES else UNKNOWN_CURRENCY


def convert_money(
    value: MoneyValue,
    target_currency: str,
    fx_provider: Callable[[str, str], Any] | dict[tuple[str, str], Any] | None,
) -> MoneyValue:
    target = normalize_currency_code(target_currency)
    if value.currency == UNKNOWN_CURRENCY or target == UNKNOWN_CURRENCY:
        raise ValueError("currency_unknown")
    if value.currency == target:
        return MoneyValue(
            amount=value.amount,
            currency=target,
            scale=value.scale,
            source_currency=value.source_currency or value.currency,
            display_currency=target,
            fx_rate=1.0,
            fx_date=value.fx_date,
            source_id=value.source_id,
            confidence=value.confidence,
            inferred_from=value.inferred_from,
        )
    fx_payload = _fx_lookup(value.currency, target, fx_provider)
    if fx_payload is None:
        raise ValueError("missing_fx_rate")
    if isinstance(fx_payload, dict):
        rate = float(fx_payload.get("rate"))
        fx_date = str(fx_payload.get("date") or "")
    else:
        rate = float(fx_payload)
        fx_date = ""
    return MoneyValue(
        amount=float(value.amount) * rate,
        currency=target,
        scale=value.scale,
        source_currency=value.currency,
        display_currency=target,
        fx_rate=rate,
        fx_date=fx_date,
        source_id=value.source_id,
        confidence=value.confidence,
        inferred_from=value.inferred_from,
    )


def format_money_for_report(value: MoneyValue, language: str = "zh-CN") -> str:
    amount = float(value.amount)
    currency = normalize_currency_code(value.display_currency or value.currency)
    if language.lower().startswith("zh"):
        names = {"CNY": "人民币", "HKD": "港元", "USD": "美元"}
        if value.scale == "billion":
            amount *= 1_000_000_000
        if abs(amount) >= 100_000_000:
            return f"{amount / 100_000_000:.2f} 亿元{names.get(currency, currency)}"
        if abs(amount) >= 10_000:
            return f"{amount / 10_000:.2f} 万元{names.get(currency, currency)}"
        return f"{amount:.2f} {names.get(currency, currency)}"
    if value.scale == "billion":
        return f"{amount:.2f} billion {currency}"
    if abs(amount) >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f} billion {currency}"
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f} million {currency}"
    return f"{amount:.2f} {currency}"


def assert_same_currency(values: Iterable[MoneyValue], context: str = "") -> str:
    currencies = {normalize_currency_code(item.currency) for item in values}
    currencies.discard(UNKNOWN_CURRENCY)
    if len(currencies) > 1:
        raise ValueError(f"currency_mismatch:{context}:{','.join(sorted(currencies))}")
    if not currencies:
        raise ValueError(f"currency_unknown:{context}")
    return next(iter(currencies))


def _fx_lookup(source: str, target: str, provider: Any) -> Any:
    if provider is None:
        return None
    if callable(provider):
        return provider(source, target)
    if isinstance(provider, dict):
        return provider.get((source, target)) or provider.get(f"{source}/{target}")
    return None
