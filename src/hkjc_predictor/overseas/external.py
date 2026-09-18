"""Stub / pluggable adapter for future non-HKJC overseas sources.

PLACEHOLDER — not implemented:
  - Racing Post style feeds
  - Racing.com style feeds

Wire a real parser here later; keep the OverseasSource contract.
"""

from __future__ import annotations

from typing import Optional

from hkjc_predictor.models import Meeting
from hkjc_predictor.overseas.sources import OverseasSource


class ExternalOverseasSource(OverseasSource):
    """Explicit stub so --source external fails clearly (not silently local)."""

    name = "external"
    label = "External (Racing Post / Racing.com placeholder — NOT IMPLEMENTED)"

    def __init__(self, requested: str = "external") -> None:
        self.requested = requested
        if requested in {"racing_post", "racing_com", "racing.com"}:
            self.name = requested.replace(".", "_")
            self.label = (
                f"PLACEHOLDER: '{requested}' adapter not implemented "
                "(Racing Post / Racing.com style — future work)"
            )

    def load_meeting(
        self,
        *,
        demo: bool = False,
        date: Optional[str] = None,
        sample_path: Optional[str] = None,
    ) -> Meeting:
        del demo, date, sample_path  # unused — stub
        raise NotImplementedError(
            f"Overseas source '{self.name}' is a PLACEHOLDER stub. "
            "Racing Post / Racing.com style adapters are not implemented yet. "
            "Use --source hkjc_simulcast --demo-overseas instead."
        )
