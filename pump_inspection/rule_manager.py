import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from .models import RuleVersion


class RuleManager:
    def __init__(self, db_session: Session, config_dir: Optional[str] = None):
        self.db = db_session
        if config_dir is None:
            config_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config"
            )
        self.config_dir = config_dir
        self._init_versions_from_files()

    def _init_versions_from_files(self):
        existing_versions = {rv.version for rv in self.db.query(RuleVersion).all()}
        has_active = any(rv.is_active for rv in self.db.query(RuleVersion).all())

        version_files = []
        for filename in os.listdir(self.config_dir):
            if filename.startswith("detection_rules_v") and filename.endswith(".json"):
                version = filename.replace("detection_rules_", "").replace(".json", "")
                version_files.append((version, filename))

        version_files.sort(key=lambda x: x[0], reverse=True)

        for version, filename in version_files:
            if version not in existing_versions:
                filepath = os.path.join(self.config_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    config = json.load(f)
                rv = RuleVersion(
                    version=version,
                    description=config.get("description", ""),
                    created_at=datetime.fromisoformat(config.get("created_at", datetime.now().isoformat())),
                    based_on=config.get("based_on"),
                    rule_config=json.dumps(config, ensure_ascii=False),
                    is_active=(not has_active)
                )
                self.db.add(rv)
                if not has_active:
                    has_active = True
        self.db.commit()

    def get_all_versions(self) -> List[RuleVersion]:
        return self.db.query(RuleVersion).order_by(RuleVersion.created_at.desc()).all()

    def get_version(self, version: str) -> Optional[RuleVersion]:
        return self.db.query(RuleVersion).filter(RuleVersion.version == version).first()

    def get_active_version(self) -> Optional[RuleVersion]:
        return self.db.query(RuleVersion).filter(RuleVersion.is_active == True).first()

    def set_active_version(self, version: str) -> bool:
        rv = self.get_version(version)
        if not rv:
            return False

        self.db.query(RuleVersion).update({RuleVersion.is_active: False})
        rv.is_active = True
        self.db.commit()
        return True

    def get_rule_config(self, version: Optional[str] = None) -> Dict:
        if version is None:
            active = self.get_active_version()
            if not active:
                return {}
            return json.loads(active.rule_config)

        rv = self.get_version(version)
        if not rv:
            return {}
        return json.loads(rv.rule_config)

    def create_new_version(self, version: str, description: str, rule_config: Dict, based_on: Optional[str] = None) -> RuleVersion:
        existing = self.get_version(version)
        if existing:
            raise ValueError(f"版本 {version} 已存在")

        rv = RuleVersion(
            version=version,
            description=description,
            created_at=datetime.now(),
            based_on=based_on,
            rule_config=json.dumps(rule_config, ensure_ascii=False),
            is_active=False
        )
        self.db.add(rv)
        self.db.commit()

        self._save_to_file(version, rule_config)
        return rv

    def _save_to_file(self, version: str, rule_config: Dict):
        filepath = os.path.join(self.config_dir, f"detection_rules_{version}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(rule_config, f, ensure_ascii=False, indent=2)

    def compare_versions(self, version1: str, version2: str) -> Dict:
        rv1 = self.get_version(version1)
        rv2 = self.get_version(version2)

        if not rv1 or not rv2:
            return {"error": "版本不存在"}

        config1 = json.loads(rv1.rule_config)
        config2 = json.loads(rv2.rule_config)

        diff = {
            "added": [],
            "removed": [],
            "modified": []
        }

        rules1 = config1.get("rules", {})
        rules2 = config2.get("rules", {})

        all_keys = set(rules1.keys()) | set(rules2.keys())
        for key in all_keys:
            if key not in rules1:
                diff["added"].append(key)
            elif key not in rules2:
                diff["removed"].append(key)
            elif rules1[key] != rules2[key]:
                diff["modified"].append({
                    "rule": key,
                    "old": rules1[key],
                    "new": rules2[key]
                })

        return diff
