"""Validated, dependency-free records for Web3 prospect intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Mapping
from urllib.parse import urlparse


_EVM_CHAINS = {
    "ethereum", "base", "arbitrum", "optimism", "polygon", "bsc",
    "avalanche", "linea", "scroll", "zksync", "mantle",
}


def _validated_http_url(value: str | None, field_name: str) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL")
    return value


def _host(value: str | None) -> str:
    if not value:
        return ""
    return (urlparse(value).hostname or "").lower().removeprefix("www.")


def _slug(value: str) -> str:
    value = value.strip().casefold()
    return re.sub(r"[^\w]+", "-", value, flags=re.UNICODE).strip("-")


@dataclass(frozen=True, slots=True)
class Evidence:
    """A traceable source observation; timestamps must include a timezone."""

    source_name: str
    source_url: str
    observed_at: str
    evidence_type: str = "discovery"
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValueError("source_name cannot be empty")
        if not self.source_url or not self.source_url.strip():
            raise ValueError("source_url must be a valid http(s) URL")
        url = _validated_http_url(self.source_url, "source_url")
        object.__setattr__(self, "source_url", url)
        try:
            parsed_time = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("observed_at must be an ISO 8601 timestamp") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("observed_at must include a timezone, such as Z or +00:00")
        if not self.evidence_type.strip():
            raise ValueError("evidence_type cannot be empty")


@dataclass(frozen=True, slots=True)
class ProspectRecord:
    """Normalized prospect data. None means unknown, never an inferred zero."""

    project_name: str
    chain: str
    contract_address: str | None = None
    website_url: str | None = None
    token_symbol: str | None = None
    metrics: Mapping[str, int | float | None] = field(default_factory=dict)
    evidence: tuple[Evidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.project_name.strip():
            raise ValueError("project_name cannot be empty")
        if not self.chain.strip():
            raise ValueError("chain cannot be empty")

        object.__setattr__(self, "project_name", self.project_name.strip())
        object.__setattr__(self, "chain", self.chain.strip())
        object.__setattr__(
            self, "contract_address",
            self.contract_address.strip() if self.contract_address and self.contract_address.strip() else None,
        )
        object.__setattr__(self, "website_url", _validated_http_url(self.website_url, "website_url"))
        object.__setattr__(self, "token_symbol", self.token_symbol.strip() if self.token_symbol and self.token_symbol.strip() else None)

        clean_metrics: dict[str, int | float | None] = {}
        for key, value in self.metrics.items():
            if not key.strip():
                raise ValueError("metric names cannot be empty")
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"metric {key!r} must be a number or None")
                if not math.isfinite(value) or value < 0:
                    raise ValueError(f"metric {key!r} must be finite and non-negative")
            clean_metrics[key.strip()] = value
        object.__setattr__(self, "metrics", clean_metrics)
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def dedupe_key(self) -> str:
        """Return a stable key; use contract identity when available."""
        chain_key = _slug(self.chain)
        if self.contract_address:
            address = self.contract_address
            if chain_key in _EVM_CHAINS:
                address = address.lower()
            return f"contract:{chain_key}:{address}"
        name_key = _slug(self.project_name)
        host_key = _host(self.website_url)
        # Keep chain in fallback identity to avoid merging unrelated deployments.
        return f"project:{chain_key}:{name_key}:{host_key}" if host_key else f"project:{chain_key}:{name_key}"
