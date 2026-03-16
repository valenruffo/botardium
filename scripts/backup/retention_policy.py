import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("botardium.retention")


@dataclass
class RetentionRule:
    rule_id: str
    backup_type: str
    min_count: int
    max_age_days: int
    priority: int = 0


@dataclass
class RetentionStats:
    rule_id: str
    backups_evaluated: int
    backups_deleted: int
    space_freed_bytes: int


class RetentionPolicy:
    DEFAULT_RULES = [
        RetentionRule(rule_id="hourly", backup_type="incremental", min_count=24, max_age_days=1, priority=100),
        RetentionRule(rule_id="daily", backup_type="incremental", min_count=7, max_age_days=7, priority=90),
        RetentionRule(rule_id="weekly_full", backup_type="full", min_count=4, max_age_days=28, priority=80),
        RetentionRule(rule_id="monthly_full", backup_type="full", min_count=12, max_age_days=365, priority=70),
    ]

    def __init__(self, retention_days: int = 30):
        self.retention_days = retention_days
        self.rules = self.DEFAULT_RULES.copy()

    def add_rule(self, rule: RetentionRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, rule_id: str) -> bool:
        original_len = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        return len(self.rules) < original_len

    def should_delete(self, backup_metadata: Any) -> bool:
        from datetime import datetime, timezone
        
        try:
            timestamp_str = backup_metadata.timestamp
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            backup_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            logger.warning(f"Could not parse timestamp: {backup_metadata.timestamp}")
            return False

        now = datetime.now(timezone.utc)
        age_days = (now - backup_time).days

        if age_days > self.retention_days:
            logger.debug(f"Backup {backup_metadata.backup_id} exceeds retention period ({age_days} > {self.retention_days})")
            return True

        return False

    def evaluate_backups(self, backups: List[Any], dry_run: bool = True) -> List[RetentionStats]:
        from scripts.backup.backup_manager import BackupManager
        
        results = []
        
        for rule in self.rules:
            matching_backups = [
                b for b in backups 
                if b.backup_type == rule.backup_type
            ]
            matching_backups.sort(key=lambda x: x.timestamp, reverse=True)

            to_delete = []
            if len(matching_backups) > rule.min_count:
                old_backups = [
                    b for b in matching_backups[rule.min_count:]
                    if self._matches_age_rule(b, rule.max_age_days)
                ]
                to_delete = old_backups

            backups_deleted = 0
            space_freed = 0
            
            for backup in to_delete:
                if not dry_run:
                    logger.info(f"Would delete backup {backup.backup_id} (rule: {rule.rule_id})")
                backups_deleted += 1
                space_freed += backup.size_bytes

            results.append(RetentionStats(
                rule_id=rule.rule_id,
                backups_evaluated=len(matching_backups),
                backups_deleted=backups_deleted,
                space_freed_bytes=space_freed
            ))

        return results

    def _matches_age_rule(self, backup_metadata: Any, max_age_days: int) -> bool:
        from datetime import datetime, timezone
        
        try:
            timestamp_str = backup_metadata.timestamp
            if timestamp_str.endswith("Z"):
                timestamp_str = timestamp_str[:-1] + "+00:00"
            backup_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return False

        now = datetime.now(timezone.utc)
        age_days = (now - backup_time).days
        return age_days > max_age_days

    def get_recommended_backups_to_keep(self, backups: List[Any]) -> List[Any]:
        recommended = []
        
        for rule in self.rules:
            matching = [b for b in backups if b.backup_type == rule.backup_type]
            matching.sort(key=lambda x: x.timestamp, reverse=True)
            recommended.extend(matching[:rule.min_count])

        seen = set()
        unique_recommended = []
        for b in recommended:
            if b.backup_id not in seen:
                seen.add(b.backup_id)
                unique_recommended.append(b)

        return unique_recommended

    def calculate_retention_schedule(self) -> Dict[str, Any]:
        return {
            "retention_days": self.retention_days,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "backup_type": r.backup_type,
                    "min_count": r.min_count,
                    "max_age_days": r.max_age_days,
                    "priority": r.priority
                }
                for r in self.rules
            ]
        }
