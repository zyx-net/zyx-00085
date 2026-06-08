import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from .models import Batch, SensorReading, Anomaly, RuleComparison, RuleVersion
from .anomaly_detector import AnomalyDetector


class RuleComparator:
    def __init__(self, db_session: Session):
        self.db = db_session

    def validate_inputs(self, batch_id: int, version1: str, version2: str) -> Tuple[bool, List[str]]:
        errors = []

        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            errors.append(f"批次 {batch_id} 不存在")
            return False, errors

        if batch.total_records == 0 or batch.status == "created":
            errors.append(f"批次 {batch_id} 尚未导入巡检数据，请先导入传感器读数")
            return False, errors

        rv1 = self.db.query(RuleVersion).filter(RuleVersion.version == version1).first()
        if not rv1:
            errors.append(f"规则版本 {version1} 不存在")

        rv2 = self.db.query(RuleVersion).filter(RuleVersion.version == version2).first()
        if not rv2:
            errors.append(f"规则版本 {version2} 不存在")

        if version1 == version2:
            errors.append("两个规则版本不能相同")

        return len(errors) == 0, errors

    def check_existing_comparison(self, batch_id: int, version1: str, version2: str) -> Optional[RuleComparison]:
        return self.db.query(RuleComparison).filter(
            RuleComparison.batch_id == batch_id,
            RuleComparison.rule_version_1 == version1,
            RuleComparison.rule_version_2 == version2
        ).first()

    def _get_or_create_detection_batch(self, original_batch: Batch, rule_version: str) -> Tuple[Batch, bool]:
        existing = self.db.query(Batch).filter(
            Batch.batch_name.like(f"comparison_{original_batch.id}_%"),
            Batch.rule_version == rule_version,
            Batch.status == "comparison"
        ).first()

        if existing and existing.total_records == original_batch.total_records:
            return existing, False

        comparison_batch = Batch(
            batch_name=f"comparison_{original_batch.id}_{rule_version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            rule_version=rule_version,
            source_file=original_batch.source_file,
            notes=f"规则对比临时批次，基于批次 {original_batch.id}，规则版本 {rule_version}",
            status="comparison",
            total_records=original_batch.total_records
        )
        self.db.add(comparison_batch)
        self.db.flush()

        readings = self.db.query(SensorReading).filter(SensorReading.batch_id == original_batch.id).all()
        for r in readings:
            new_reading = SensorReading(
                batch_id=comparison_batch.id,
                raw_row_index=r.raw_row_index,
                device_id=r.device_id,
                reading_time=r.reading_time,
                water_pressure=r.water_pressure,
                flow_rate=r.flow_rate,
                temperature=r.temperature,
                status=r.status,
                inspector=r.inspector,
                raw_data=r.raw_data,
                time_zone=r.time_zone
            )
            self.db.add(new_reading)

        self.db.commit()
        self.db.refresh(comparison_batch)
        return comparison_batch, True

    def _get_anomalies_for_version(self, original_batch: Batch, rule_version: str) -> Tuple[List[Anomaly], str, bool]:
        if original_batch.rule_version == rule_version and original_batch.status in ["detected", "reviewed"]:
            anomalies = self.db.query(Anomaly).filter(Anomaly.batch_id == original_batch.id).all()
            return anomalies, f"batch_{original_batch.id}", False

        comparison_batch, created = self._get_or_create_detection_batch(original_batch, rule_version)

        if created or comparison_batch.anomaly_count == 0:
            from .rule_manager import RuleManager
            rule_manager = RuleManager(self.db)
            rule_config = rule_manager.get_rule_config(rule_version)
            if not rule_config:
                raise ValueError(f"无法加载规则版本 {rule_version} 的配置")

            detector = AnomalyDetector(self.db, rule_config)
            anomalies = detector.detect_all(comparison_batch.id)

            for a in anomalies:
                self.db.add(a)

            comparison_batch.anomaly_count = len(anomalies)
            comparison_batch.status = "comparison"
            self.db.commit()
            self.db.refresh(comparison_batch)
        else:
            anomalies = self.db.query(Anomaly).filter(Anomaly.batch_id == comparison_batch.id).all()

        return anomalies, f"batch_{comparison_batch.id}", created

    def _anomaly_key(self, anomaly: Anomaly) -> str:
        return f"{anomaly.anomaly_code}|{anomaly.device_id}|{anomaly.reading_time.isoformat() if anomaly.reading_time else 'None'}"

    def compare(self, batch_id: int, version1: str, version2: str, force: bool = False) -> Tuple[Optional[RuleComparison], List[str]]:
        valid, errors = self.validate_inputs(batch_id, version1, version2)
        if not valid:
            return None, errors

        existing = self.check_existing_comparison(batch_id, version1, version2)
        if existing and not force:
            return None, [
                f"该批次的 {version1} 与 {version2} 对比结果已存在（创建于 {existing.created_at}）。",
                f"如需重新生成，请添加 --force 参数覆盖，或使用 --output 指定不同的文件名前缀。"
            ]

        if existing and force:
            self.db.delete(existing)
            self.db.commit()

        original_batch = self.db.query(Batch).filter(Batch.id == batch_id).first()

        try:
            anomalies_v1, source_v1, created_v1 = self._get_anomalies_for_version(original_batch, version1)
            anomalies_v2, source_v2, created_v2 = self._get_anomalies_for_version(original_batch, version2)
        except (json.JSONDecodeError, ValueError) as e:
            return None, [f"规则配置读取失败: {str(e)}"]
        except FileNotFoundError as e:
            return None, [f"规则配置文件不存在: {str(e)}"]

        comparison_data = self._build_comparison_data(
            original_batch, version1, version2,
            anomalies_v1, anomalies_v2,
            source_v1, source_v2, created_v1, created_v2
        )

        try:
            comparison = RuleComparison(
                batch_id=batch_id,
                rule_version_1=version1,
                rule_version_2=version2,
                comparison_data=json.dumps(comparison_data, ensure_ascii=False)
            )
            self.db.add(comparison)
            self.db.commit()
            self.db.refresh(comparison)
            return comparison, []
        except IntegrityError:
            self.db.rollback()
            existing = self.check_existing_comparison(batch_id, version1, version2)
            if existing and force:
                self.db.delete(existing)
                self.db.commit()
                comparison = RuleComparison(
                    batch_id=batch_id,
                    rule_version_1=version1,
                    rule_version_2=version2,
                    comparison_data=json.dumps(comparison_data, ensure_ascii=False)
                )
                self.db.add(comparison)
                self.db.commit()
                self.db.refresh(comparison)
                return comparison, []
            return None, ["保存对比结果时发生冲突，请稍后重试或使用 --force 参数"]

    def _build_comparison_data(
        self,
        original_batch: Batch,
        version1: str, version2: str,
        anomalies_v1: List[Anomaly], anomalies_v2: List[Anomaly],
        source_v1: str, source_v2: str,
        created_v1: bool, created_v2: bool
    ) -> Dict:
        keys_v1 = {self._anomaly_key(a): a for a in anomalies_v1}
        keys_v2 = {self._anomaly_key(a): a for a in anomalies_v2}

        all_keys = set(keys_v1.keys()) | set(keys_v2.keys())
        only_v1 = [k for k in all_keys if k in keys_v1 and k not in keys_v2]
        only_v2 = [k for k in all_keys if k in keys_v2 and k not in keys_v1]
        in_both = [k for k in all_keys if k in keys_v1 and k in keys_v2]

        severity_changes = []
        for k in in_both:
            a1 = keys_v1[k]
            a2 = keys_v2[k]
            if a1.severity != a2.severity:
                severity_changes.append({
                    "key": k,
                    "anomaly_code": a1.anomaly_code,
                    "anomaly_type": a1.anomaly_type,
                    "device_id": a1.device_id,
                    "reading_time": a1.reading_time.isoformat() if a1.reading_time else None,
                    "severity_v1": a1.severity,
                    "severity_v2": a2.severity,
                    "description": a1.description
                })

        def summarize_by_type(anomalies: List[Anomaly]) -> Dict:
            summary = {}
            for a in anomalies:
                code = a.anomaly_code
                if code not in summary:
                    summary[code] = {
                        "异常类型": a.anomaly_type,
                        "异常代码": code,
                        "数量": 0,
                        "严重级别分布": {}
                    }
                summary[code]["数量"] += 1
                sev = a.severity
                summary[code]["严重级别分布"][sev] = summary[code]["严重级别分布"].get(sev, 0) + 1
            return summary

        def summarize_by_severity(anomalies: List[Anomaly]) -> Dict:
            summary = {}
            for a in anomalies:
                sev = a.severity
                summary[sev] = summary.get(sev, 0) + 1
            return summary

        def anomaly_to_dict(a: Anomaly, version: str) -> Dict:
            return {
                "规则版本": version,
                "异常ID": a.id,
                "异常类型": a.anomaly_type,
                "异常代码": a.anomaly_code,
                "严重程度": a.severity,
                "设备编号": a.device_id,
                "读数时间": a.reading_time.isoformat() if a.reading_time else None,
                "描述": a.description,
                "预期值": a.expected_value,
                "实际值": a.actual_value,
                "原始行号": a.reading.raw_row_index if a.reading else None
            }

        return {
            "meta": {
                "batch_id": original_batch.id,
                "batch_name": original_batch.batch_name,
                "rule_version_1": version1,
                "rule_version_2": version2,
                "total_records": original_batch.total_records,
                "source_file": original_batch.source_file,
                "comparison_time": datetime.now().isoformat(),
                "detection_source_v1": source_v1,
                "detection_source_v2": source_v2,
                "detection_newly_run_v1": created_v1,
                "detection_newly_run_v2": created_v2,
            },
            "totals": {
                "version1_total": len(anomalies_v1),
                "version2_total": len(anomalies_v2),
                "difference": len(anomalies_v2) - len(anomalies_v1),
                "only_in_version1": len(only_v1),
                "only_in_version2": len(only_v2),
                "in_both_versions": len(in_both),
                "severity_changes": len(severity_changes)
            },
            "by_type_v1": summarize_by_type(anomalies_v1),
            "by_type_v2": summarize_by_type(anomalies_v2),
            "by_severity_v1": summarize_by_severity(anomalies_v1),
            "by_severity_v2": summarize_by_severity(anomalies_v2),
            "severity_changes": severity_changes,
            "only_in_version1": [anomaly_to_dict(keys_v1[k], version1) for k in only_v1],
            "only_in_version2": [anomaly_to_dict(keys_v2[k], version2) for k in only_v2],
        }

    def load_comparison(self, comparison_id: int) -> Optional[Dict]:
        comparison = self.db.query(RuleComparison).filter(RuleComparison.id == comparison_id).first()
        if not comparison:
            return None
        try:
            return json.loads(comparison.comparison_data)
        except json.JSONDecodeError:
            return None

    def get_comparison_by_key(self, batch_id: int, version1: str, version2: str) -> Optional[Dict]:
        comparison = self.check_existing_comparison(batch_id, version1, version2)
        if not comparison:
            return None
        try:
            return json.loads(comparison.comparison_data)
        except json.JSONDecodeError:
            return None

    def update_output_prefix(self, comparison_id: int, prefix: str) -> bool:
        comparison = self.db.query(RuleComparison).filter(RuleComparison.id == comparison_id).first()
        if not comparison:
            return False
        comparison.output_file_prefix = prefix
        self.db.commit()
        return True
