"""Kuzu embedded graph database for knowledge graph."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        self._entity_id_enabled = self._detect_entity_id_column()

    def _detect_entity_id_column(self) -> bool:
        """Detect whether the Entity table includes entity_id (new schema)."""
        try:
            self._conn.execute("MATCH (e:Entity) RETURN e.entity_id LIMIT 1")
            return True
        except Exception:
            logger.warning(
                "Entity table is using a legacy schema without entity_id. "
                "Scoped duplicate entity names will not be supported until migration."
            )
            return False

    def _init_schema(self) -> None:
        """Create node and relationship tables if they don't exist."""
        try:
            self._conn.execute(
                "CREATE NODE TABLE IF NOT EXISTS Entity("
                "entity_id STRING, "
                "name STRING, "
                "entity_type STRING, "
                "observations STRING, "
                "scope STRING, "
                "created_at STRING, "
                "updated_at STRING, "
                "PRIMARY KEY (entity_id))"
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

    def _entity_fields_projection(self) -> str:
        """Return a consistent projection for entity rows across schema versions."""
        if self._entity_id_enabled:
            return (
                "e.entity_id, e.name, e.entity_type, e.observations, "
                "e.scope, e.created_at, e.updated_at"
            )
        return "'' as entity_id, e.name, e.entity_type, e.observations, e.scope, e.created_at, e.updated_at"

    def _read_single_entity_record(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        """Read one entity record by name, optionally scoped."""
        conditions = ["e.name = $name"]
        params: dict[str, Any] = {"name": name}
        if scope:
            conditions.append("e.scope = $scope")
            params["scope"] = scope

        query = (
            f"MATCH (e:Entity) WHERE {' AND '.join(conditions)} "
            f"RETURN {self._entity_fields_projection()} "
            "ORDER BY e.updated_at DESC LIMIT 1"
        )
        result = self._conn.execute(query, params)
        if not result.has_next():
            return None

        row = result.get_next()
        return {
            "entity_id": row[0] or None,
            "name": row[1],
            "entity_type": row[2],
            "observations": row[3].split("|") if row[3] else [],
            "scope": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }

    def _count(self, query: str, params: dict[str, Any] | None = None) -> int:
        """Execute a count query and return the scalar result."""
        result = self._conn.execute(query, params or {})
        if result.has_next():
            return int(result.get_next()[0])
        return 0

    @property
    def schema_version(self) -> str:
        """Return the graph schema version label."""
        return "v2" if self._entity_id_enabled else "legacy"

    def is_legacy_schema(self) -> bool:
        """Return True when running on the legacy graph schema."""
        return not self._entity_id_enabled

    def migrate_legacy_schema(self, backup_path: str | Path | None = None) -> dict[str, Any]:
        """Migrate legacy graph schema to v2 with entity_id primary keys."""
        if self._entity_id_enabled:
            return {
                "migrated": False,
                "schema_version": self.schema_version,
                "reason": "already_v2",
            }

        entities: list[dict[str, Any]] = []
        result = self._conn.execute(
            "MATCH (e:Entity) "
            "RETURN e.name, e.entity_type, e.observations, e.scope, e.created_at, e.updated_at"
        )
        while result.has_next():
            row = result.get_next()
            entities.append({
                "name": row[0],
                "entity_type": row[1],
                "observations": row[2] or "",
                "scope": row[3] or "global",
                "created_at": row[4] or "",
                "updated_at": row[5] or "",
            })

        relations: list[dict[str, Any]] = []
        result = self._conn.execute(
            "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
            "RETURN a.name, a.scope, b.name, b.scope, r.relation_type, r.scope, r.created_at"
        )
        while result.has_next():
            row = result.get_next()
            relations.append({
                "source": row[0],
                "source_scope": row[1] or "global",
                "target": row[2],
                "target_scope": row[3] or "global",
                "relation_type": row[4],
                "scope": row[5] or "global",
                "created_at": row[6] or "",
            })

        snapshot = {
            "schema": "legacy",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "entities": entities,
            "relations": relations,
        }
        if backup_path is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_file = self._db_path.parent / f"{self._db_path.name}_legacy_backup_{ts}.json"
        else:
            backup_file = Path(backup_path)
        backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup_file.write_text(json.dumps(snapshot, indent=2))

        try:
            self._conn.execute("DROP TABLE Relation")
            self._conn.execute("DROP TABLE Entity")
            self._init_schema()
            self._entity_id_enabled = self._detect_entity_id_column()
            if not self._entity_id_enabled:
                raise RuntimeError("Failed to initialize v2 graph schema during migration")

            id_by_scope_name: dict[tuple[str, str], str] = {}
            id_by_name: dict[str, str] = {}
            for entity in entities:
                entity_id = str(uuid4())
                self._conn.execute(
                    "CREATE (e:Entity {entity_id: $entity_id, name: $name, entity_type: $type, "
                    "observations: $obs, scope: $scope, created_at: $created_at, updated_at: $updated_at})",
                    {
                        "entity_id": entity_id,
                        "name": entity["name"],
                        "type": entity["entity_type"],
                        "obs": entity["observations"],
                        "scope": entity["scope"],
                        "created_at": entity["created_at"],
                        "updated_at": entity["updated_at"],
                    },
                )
                id_by_scope_name[(entity["scope"], entity["name"])] = entity_id
                id_by_name[entity["name"]] = entity_id

            migrated_relations = 0
            skipped_relations = 0
            for rel in relations:
                src_id = id_by_scope_name.get((rel["source_scope"], rel["source"])) or id_by_name.get(rel["source"])
                tgt_id = id_by_scope_name.get((rel["target_scope"], rel["target"])) or id_by_name.get(rel["target"])
                if not src_id or not tgt_id:
                    skipped_relations += 1
                    continue

                self._conn.execute(
                    "MATCH (a:Entity), (b:Entity) "
                    "WHERE a.entity_id = $src_id AND b.entity_id = $tgt_id "
                    "CREATE (a)-[:Relation {relation_type: $rtype, scope: $scope, created_at: $created_at}]->(b)",
                    {
                        "src_id": src_id,
                        "tgt_id": tgt_id,
                        "rtype": rel["relation_type"],
                        "scope": rel["scope"],
                        "created_at": rel["created_at"],
                    },
                )
                migrated_relations += 1

            return {
                "migrated": True,
                "schema_version": self.schema_version,
                "backup_path": str(backup_file),
                "entities_migrated": len(entities),
                "relations_migrated": migrated_relations,
                "relations_skipped": skipped_relations,
            }
        except Exception as e:
            logger.exception("Legacy graph schema migration failed")
            return {
                "migrated": False,
                "schema_version": self.schema_version,
                "backup_path": str(backup_file),
                "error": str(e),
            }

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

        if self._read_single_entity_record(name, scope=scope):
            return False

        try:
            if self._entity_id_enabled:
                self._conn.execute(
                    "CREATE (e:Entity {entity_id: $entity_id, name: $name, entity_type: $type, "
                    "observations: $obs, scope: $scope, created_at: $now, updated_at: $now})",
                    {
                        "entity_id": str(uuid4()),
                        "name": name,
                        "type": entity_type,
                        "obs": obs_json,
                        "scope": scope,
                        "now": now,
                    },
                )
            else:
                self._conn.execute(
                    "CREATE (e:Entity {name: $name, entity_type: $type, "
                    "observations: $obs, scope: $scope, created_at: $now, updated_at: $now})",
                    {"name": name, "type": entity_type, "obs": obs_json, "scope": scope, "now": now},
                )
            return True
        except Exception as e:
            logger.debug(f"Entity create failed (may exist): {e}")
            return False

    def get_entity(self, name: str, scope: str | None = None) -> dict[str, Any] | None:
        """Get an entity by name."""
        record = self._read_single_entity_record(name, scope=scope)
        if not record:
            return None
        return {
            "name": record["name"],
            "entity_type": record["entity_type"],
            "observations": record["observations"],
            "scope": record["scope"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
        }

    def update_entity(self, name: str, scope: str | None = None, **updates: Any) -> bool:
        """Update entity fields."""
        from datetime import datetime, timezone

        entity = self._read_single_entity_record(name, scope=scope)
        if not entity:
            return False

        if "observations" in updates and isinstance(updates["observations"], list):
            updates["observations"] = "|".join(updates["observations"])

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        if not updates:
            return True

        set_clauses = []
        params: dict[str, Any] = {}
        for key, value in updates.items():
            set_clauses.append(f"e.{key} = ${key}")
            params[key] = value

        if self._entity_id_enabled and entity["entity_id"]:
            params["entity_id"] = entity["entity_id"]
            query = f"MATCH (e:Entity) WHERE e.entity_id = $entity_id SET {', '.join(set_clauses)}"
        else:
            params["name"] = name
            params["scope"] = entity["scope"]
            query = f"MATCH (e:Entity) WHERE e.name = $name AND e.scope = $scope SET {', '.join(set_clauses)}"
        self._conn.execute(query, params)
        return True

    def delete_entity(self, name: str, scope: str | None = None) -> bool:
        """Delete an entity and all its relations."""
        entity = self._read_single_entity_record(name, scope=scope)
        if not entity:
            return False

        try:
            if self._entity_id_enabled and entity["entity_id"]:
                entity_id = entity["entity_id"]
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE a.entity_id = $entity_id DELETE r",
                    {"entity_id": entity_id},
                )
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE b.entity_id = $entity_id DELETE r",
                    {"entity_id": entity_id},
                )
                self._conn.execute(
                    "MATCH (e:Entity) WHERE e.entity_id = $entity_id DELETE e",
                    {"entity_id": entity_id},
                )
            else:
                params = {"name": name, "scope": entity["scope"]}
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE a.name = $name AND a.scope = $scope DELETE r",
                    params,
                )
                self._conn.execute(
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) WHERE b.name = $name AND b.scope = $scope DELETE r",
                    params,
                )
                self._conn.execute(
                    "MATCH (e:Entity) WHERE e.name = $name AND e.scope = $scope DELETE e",
                    params,
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
        query = f"MATCH (e:Entity){where} RETURN {self._entity_fields_projection()} LIMIT {limit}"

        result = self._conn.execute(query, params)
        entities = []
        while result.has_next():
            row = result.get_next()
            entities.append({
                "name": row[1],
                "entity_type": row[2],
                "observations": row[3].split("|") if row[3] else [],
                "scope": row[4],
                "created_at": row[5],
                "updated_at": row[6],
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

        source_entity = self._read_single_entity_record(source, scope=scope)
        target_entity = self._read_single_entity_record(target, scope=scope)
        if not source_entity or not target_entity:
            return False

        if self._entity_id_enabled and source_entity["entity_id"] and target_entity["entity_id"]:
            relation_count = self._count(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.entity_id = $src_id AND b.entity_id = $tgt_id "
                "AND r.relation_type = $rtype AND r.scope = $scope "
                "RETURN count(r)",
                {
                    "src_id": source_entity["entity_id"],
                    "tgt_id": target_entity["entity_id"],
                    "rtype": relation_type,
                    "scope": scope,
                },
            )
        else:
            relation_count = self._count(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt AND a.scope = $scope AND b.scope = $scope "
                "AND r.relation_type = $rtype AND r.scope = $scope "
                "RETURN count(r)",
                {"src": source, "tgt": target, "rtype": relation_type, "scope": scope},
            )

        if relation_count > 0:
            return False

        now = datetime.now(timezone.utc).isoformat()
        try:
            if self._entity_id_enabled and source_entity["entity_id"] and target_entity["entity_id"]:
                self._conn.execute(
                    "MATCH (a:Entity), (b:Entity) "
                    "WHERE a.entity_id = $src_id AND b.entity_id = $tgt_id "
                    "CREATE (a)-[:Relation {relation_type: $rtype, scope: $scope, created_at: $now}]->(b)",
                    {
                        "src_id": source_entity["entity_id"],
                        "tgt_id": target_entity["entity_id"],
                        "rtype": relation_type,
                        "scope": scope,
                        "now": now,
                    },
                )
            else:
                self._conn.execute(
                    "MATCH (a:Entity), (b:Entity) "
                    "WHERE a.name = $src AND b.name = $tgt AND a.scope = $scope AND b.scope = $scope "
                    "CREATE (a)-[:Relation {relation_type: $rtype, scope: $scope, created_at: $now}]->(b)",
                    {"src": source, "tgt": target, "rtype": relation_type, "scope": scope, "now": now},
                )
            return True
        except Exception as e:
            logger.debug(f"Relation create failed: {e}")
            return False

    def delete_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        scope: str | None = None,
    ) -> bool:
        """Delete a specific relation."""
        if scope:
            source_entity = self._read_single_entity_record(source, scope=scope)
            target_entity = self._read_single_entity_record(target, scope=scope)
            if not source_entity or not target_entity:
                return False

            if self._entity_id_enabled and source_entity["entity_id"] and target_entity["entity_id"]:
                count_query = (
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                    "WHERE a.entity_id = $src_id AND b.entity_id = $tgt_id "
                    "AND r.relation_type = $rtype AND r.scope = $scope "
                    "RETURN count(r)"
                )
                delete_query = (
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                    "WHERE a.entity_id = $src_id AND b.entity_id = $tgt_id "
                    "AND r.relation_type = $rtype AND r.scope = $scope DELETE r"
                )
                params = {
                    "src_id": source_entity["entity_id"],
                    "tgt_id": target_entity["entity_id"],
                    "rtype": relation_type,
                    "scope": scope,
                }
            else:
                count_query = (
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                    "WHERE a.name = $src AND b.name = $tgt AND a.scope = $scope AND b.scope = $scope "
                    "AND r.relation_type = $rtype AND r.scope = $scope "
                    "RETURN count(r)"
                )
                delete_query = (
                    "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                    "WHERE a.name = $src AND b.name = $tgt AND a.scope = $scope AND b.scope = $scope "
                    "AND r.relation_type = $rtype AND r.scope = $scope DELETE r"
                )
                params = {"src": source, "tgt": target, "rtype": relation_type, "scope": scope}
        else:
            count_query = (
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt AND r.relation_type = $rtype "
                "RETURN count(r)"
            )
            delete_query = (
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                "WHERE a.name = $src AND b.name = $tgt AND r.relation_type = $rtype "
                "DELETE r"
            )
            params = {"src": source, "tgt": target, "rtype": relation_type}

        try:
            if self._count(count_query, params) == 0:
                return False
            self._conn.execute(delete_query, params)
            return True
        except Exception as e:
            logger.debug(f"Relation delete failed: {e}")
            return False

    def get_relations(
        self,
        entity_name: str,
        direction: str = "both",
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all relations for an entity."""
        relations = []

        where_out = ["a.name = $name"]
        where_in = ["b.name = $name"]
        params: dict[str, Any] = {"name": entity_name}
        if scope:
            where_out.extend(["a.scope = $scope", "r.scope = $scope"])
            where_in.extend(["b.scope = $scope", "r.scope = $scope"])
            params["scope"] = scope

        if direction in ("out", "both"):
            result = self._conn.execute(
                "MATCH (a:Entity)-[r:Relation]->(b:Entity) "
                f"WHERE {' AND '.join(where_out)} "
                "RETURN a.name, r.relation_type, b.name, r.scope, r.created_at",
                params,
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
                f"WHERE {' AND '.join(where_in)} "
                "RETURN a.name, r.relation_type, b.name, r.scope, r.created_at",
                params,
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
        scope: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """Find shortest path between two entities."""
        try:
            hops = max(1, int(max_hops))
            where_conditions = ["a.name = $src", "b.name = $tgt"]
            params: dict[str, Any] = {"src": source, "tgt": target}
            if scope:
                where_conditions.extend(["a.scope = $scope", "b.scope = $scope"])
                params["scope"] = scope

            result = self._conn.execute(
                f"MATCH p = (a:Entity)-[:Relation*1..{hops}]->(b:Entity) "
                f"WHERE {' AND '.join(where_conditions)} "
                "RETURN nodes(p), rels(p) LIMIT 1",
                params,
            )
            if result.has_next():
                row = result.get_next()
                return {"nodes": row[0], "relations": row[1]}
        except Exception as e:
            logger.debug(f"Path finding failed: {e}")
        return None

    def entity_count(self, scope: str | None = None) -> int:
        """Count total entities."""
        if scope:
            return self._count("MATCH (e:Entity) WHERE e.scope = $scope RETURN count(e)", {"scope": scope})
        return self._count("MATCH (e:Entity) RETURN count(e)")

    def relation_count(self, scope: str | None = None) -> int:
        """Count total relations."""
        if scope:
            return self._count("MATCH ()-[r:Relation]->() WHERE r.scope = $scope RETURN count(r)", {"scope": scope})
        return self._count("MATCH ()-[r:Relation]->() RETURN count(r)")

    def add_observations(self, entity_name: str, observations: list[str], scope: str | None = None) -> bool:
        """Add observations to an existing entity."""
        entity = self.get_entity(entity_name, scope=scope)
        if not entity:
            return False
        existing = entity.get("observations", [])
        combined = existing + observations
        return self.update_entity(entity_name, scope=scope, observations=combined)

    def remove_observations(self, entity_name: str, observations: list[str], scope: str | None = None) -> bool:
        """Remove specific observations from an entity."""
        entity = self.get_entity(entity_name, scope=scope)
        if not entity:
            return False
        existing = entity.get("observations", [])
        updated = [o for o in existing if o not in observations]
        return self.update_entity(entity_name, scope=scope, observations=updated)

    def delete_scope(self, scope: str) -> dict[str, int]:
        """Delete all entities and relations in a given scope."""
        entities = self.entity_count(scope=scope)
        relations = self.relation_count(scope=scope)
        try:
            self._conn.execute(
                "MATCH ()-[r:Relation]->() WHERE r.scope = $scope DELETE r",
                {"scope": scope},
            )
            self._conn.execute(
                "MATCH (e:Entity) WHERE e.scope = $scope DELETE e",
                {"scope": scope},
            )
        except Exception as e:
            logger.debug(f"Scope delete failed for {scope}: {e}")
            return {"entities_deleted": 0, "relations_deleted": 0}
        return {"entities_deleted": entities, "relations_deleted": relations}
