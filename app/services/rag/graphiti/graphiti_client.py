"""
Graphiti client bootstrap.

Phase 1 goal:
- Centralize provider initialization for Graphiti stack.
- Keep a lightweight wrapper so later phases can swap internals without touching call-sites.
"""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import Driver, GraphDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)


class GraphitiClient:
    """Connection manager for Graphiti graph backend (Neo4j in current setup)."""

    def __init__(self) -> None:
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.GRAPHITI_URI,
                auth=(settings.GRAPHITI_USERNAME, settings.GRAPHITI_PASSWORD),
            )
        return self._driver

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


graphiti_client = GraphitiClient()

