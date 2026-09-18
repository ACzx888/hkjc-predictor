"""Pluggable overseas data source adapters (protocol / ABC)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from hkjc_predictor.models import Meeting


class OverseasSource(ABC):
    """Adapter contract for overseas / simulcast meeting data."""

    name: str = "base"
    label: str = "Overseas source"

    @abstractmethod
    def load_meeting(
        self,
        *,
        demo: bool = False,
        date: Optional[str] = None,
        sample_path: Optional[str] = None,
    ) -> Meeting:
        """Return a Meeting. Never pulls local HK race cards."""

    def describe(self) -> str:
        return f"Source adapter: {self.name} ({self.label})"


def get_source(name: str = "hkjc_simulcast") -> OverseasSource:
    key = (name or "hkjc_simulcast").strip().lower()
    if key in {"hkjc_simulcast", "hkjc", "simulcast"}:
        from hkjc_predictor.overseas.hkjc_simulcast import HkjcSimulcastSource

        return HkjcSimulcastSource()
    if key in {"external", "racing_post", "racing_com", "racing.com"}:
        from hkjc_predictor.overseas.external import ExternalOverseasSource

        return ExternalOverseasSource(requested=key)
    raise ValueError(
        f"Unknown overseas source '{name}'. Available: {', '.join(list_sources())}"
    )


def list_sources() -> list[str]:
    return ["hkjc_simulcast", "external"]
