"""Application context: the stores and the gateway the services share."""

from __future__ import annotations

from typing import Optional

from .gateway import LLMGateway
from .store import Stores, open_stores


class AppContext:
    def __init__(self, stores: Optional[Stores] = None,
                 gateway: Optional[LLMGateway] = None,
                 db_path: Optional[str] = None) -> None:
        self.stores = stores or open_stores(db_path)
        self.gateway = gateway or LLMGateway(audit=self.stores.audit)
        if self.gateway.audit is None:
            self.gateway.audit = self.stores.audit

    # Display aliases never leave the boundary (C-02). The prototype stores only
    # an opaque student_ref, so the map is empty unless a caller supplies one.
    aliases: dict[str, str] = {}
