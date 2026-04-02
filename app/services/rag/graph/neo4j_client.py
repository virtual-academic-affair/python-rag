"""
Neo4j client singleton for GraphRAG storage.
"""

from __future__ import annotations

import logging
from typing import Optional

from neo4j import GraphDatabase, Driver

from app.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Lightweight Neo4j driver manager."""

    def __init__(self) -> None:
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        return self._driver

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


neo4j_client = Neo4jClient()

