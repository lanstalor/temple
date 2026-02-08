"""Kuzu embedded graph database for knowledge graph."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import kuzu

logger = logging.getLogger(__name__)


class GraphStore:
    """Kuzu-backed embedded knowledge graph."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        # Kuzu manages its own directory - only ensure parent exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self._db_path))
        self._conn = kuzu.Connection(self._db)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create node and relationship tables if they don't exist."""
        try:
            self._conn.execute(
                "CREATE NODE TABLE IF NOT EXISTS Entity("
                "name STRING, "
                "entity_type STRING, "
                "observations STRING, "
                "scope STRING, "
                "created_at STRING, "
                "updated_at STRING, "
                "PRIMARY KEY (name))"
            )
            self._conn.execute(
                "CREATE REL TABLE IF NOT EXISTS Relation("
                "FROM Entity TO Entity, "
                "relation_type STRING, "
                "scope STRING, "
                "created_at STRING)"
            )
        except Exception as e:
            logger.debug(f"Schema init note: {e}")

    def create_entity(
        self,
        name: str,
        entity_type: str,
        observations: list[str] | None = None,
        scope: str = "global",
    ) -> bool:
        """Create an entity node. Returns True if created, False if exists."""
        from datetime import datetime, timezone

        obs_json = "|".join(observations or [])
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "CREATE (e:Entity {name: $name, entity_type: $type, "
                "observations: $obs, scope: $scope, "
                "created_at: $now, updated_at: $now})",
                {"name": name, "type": entity_type, "obs": obs_json, "scope": scope, "now": now},
            )
            return True
        except Exception as e:
            logger.debug(f"Entity create failed (may exist): {e}")
            return False

    def get_entity(self, name: str) -> dict[str, Any] | None:
        """Get an entity by name."""
        result = self._conn.execute(
            "MATCH (e:Entity) WHERE e.name = $name RETURN e.*",
            {"name": name},
        )
        while result.has_next():
            row = result.get_next()
            return {
                "name": row[0],
                "entity_type": row[1],
                "observations": row[2].split("|") if row[2] else [],
                "scope": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            }
        return None

    def update_entity(self, name: str, **updates: Any) -> bool:
        """Update entity fields."""
        from datetime import datetime, timezone

        entity = self.get_entity(name)
        if not entity:
            return False

        if "observations" in updates and isinstance(updates["observations"], list):
            updates["observations"] = "|".join(updates["observations"])

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        set_clauses = []
        params: dict[str, Any] = {"name": name}
        for key, value in updates.items():
            set_clauses.append(f"e.{key} = ${key}")
            params[key] = value

        if set_clauses:
            query = f"MATCH (e:Entity) WHERE e.name = $name SET {', '.join(set_clauses)}"
            self._conn.execute(query, params)
        return True

    def delete_entity(self, name: str) -> bool:
        """Delete an entity and all its relations."""
        try:
            # Delete outgoing relations
            try:
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE a.name = $name DELETE r",
                    {"name": name},
                )
            except Exception:
                pass
            # Delete incoming relations
            try:
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE b.name = $name DELETE r",
                    {"name": name},
                )
            except Exception:
                pass
            # Delete entity
            self._conn.execute(
                "MATCH (e:Entity) WHERE e.name = $name DELETE e",
                {"name": name},
            )
            return True
        except Exception as e:
            logger.debug(f"Entity delete failed: {e}")
            return False

    def search_entities(
        self,
        entity_type: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search entities by type and/or scope."""
        conditions = []
        params: dict[str, Any] = {}

        if entity_type:
            conditions.append("e.entity_type = $type")
            params["type"] = entity_type
        if scope:
            conditions.append("e.scope = $scope")
            params["scope"] = scope

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"MATCH (e:Entity){where} RETURN e.* LIMIT {limit}"

        result = self._conn.execute(query, params)
        entities = []
        while result.has_next():
            row = result.get_next()
            entities.append({
                "name": row[0],
                "entity_type": row[1],
                "observations": row[2].split("|") if row[2] else [],
                "scope": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            })
        return entities

    def create_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        scope: str = "global",
    ) -> bool:
        """Create a relation between two entities."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "MATCH (a:Entity), (b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt "
                "CREATE (a)-[:Relation {relation_type: $rtype, scope: $scope, created_at: $now}]->(b)",
                {"src": source, "tgt": target, "rtype": relation_type, "scope": scope, "now": now},
            )
            return True
        except Exception as e:
            logger.debug(f"Relation create failed: {e}")
            return False

    def delete_relation(self, source: str, target: str, relation_type: str) -> bool:
        """Delete a specific relation."""
        try:
            self._conn.execute(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt AND r.relation_type = $rtype "
                "DELETE r",
                {"src": source, "tgt": target, "rtype": relation_type},
            )
            return True
        except Exception as e:
            logger.debug(f"Relation delete failed: {e}")
            return False

    def get_relations(
        self,
        entity_name: str,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity."""
        relations = []

        if direction in ("out", "both"):
            result = self._conn.execute(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.name = $name "
                "RETURN a.name, r.relation_type, b.name, r.scope, r.created_at",
                {"name": entity_name},
            )
            while result.has_next():
                row = result.get_next()
                relations.append({
                    "source": row[0],
                    "relation_type": row[1],
                    "target": row[2],
                    "scope": row[3],
                    "created_at": row[4],
                    "direction": "out",
                })

        if direction in ("in", "both"):
            result = self._conn.execute(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE b.name = $name "
                "RETURN a.name, r.relation_type, b.name, r.scope, r.created_at",
                {"name": entity_name},
            )
            while result.has_next():
                row = result.get_next()
                relations.append({
                    "source": row[0],
                    "relation_type": row[1],
                    "target": row[2],
                    "scope": row[3],
                    "created_at": row[4],
                    "direction": "in",
                })

        return relations

    def find_path(
        self,
        source: str,
        target: str,
        max_hops: int = 5,
    ) -> list[dict[str, Any]] | None:
        """Find shortest path between two entities."""
        try:
            result = self._conn.execute(
                f"MATCH p = (a:Entity)-[:Relation* ..{max_hops}]->(b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt "
                "RETURN nodes(p), rels(p) LIMIT 1",
                {"src": source, "tgt": target},
            )
            if result.has_next():
                row = result.get_next()
                return {"nodes": row[0], "relations": row[1]}
        except Exception as e:
            logger.debug(f"Path finding failed: {e}")
        return None

    def entity_count(self) -> int:
        """Count total entities."""
        result = self._conn.execute("MATCH (e:Entity) RETURN count(e)")
        if result.has_next():
            return result.get_next()[0]
        return 0

    def relation_count(self) -> int:
        """Count total relations."""
        result = self._conn.execute("MATCH ()-[r:Relation]->() RETURN count(r)")
        if result.has_next():
            return result.get_next()[0]
        return 0

    def add_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Add observations to an existing entity."""
        entity = self.get_entity(entity_name)
        if not entity:
            return False
        existing = entity.get("observations", [])
        combined = existing + observations
        return self.update_entity(entity_name, observations=combined)

    def remove_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Remove specific observations from an entity."""
        entity = self.get_entity(entity_name)
        if not entity:
            return False
        existing = entity.get("observations", [])
        updated = [o for o in existing if o not in observations]
        return self.update_entity(entity_name, observations=updated)
