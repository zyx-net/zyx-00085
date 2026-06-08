import pandas as pd
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from .models import Batch, SensorReading, InspectionShift, EquipmentLedger, Anomaly, ReviewRecord
from .field_mapper import FieldMapper
from .validator import DataValidator
from .anomaly_detector import AnomalyDetector


class BatchManager:
    def __init__(self, db_session: Session):
        self.db = db_session
        self.field_mapper = FieldMapper()
        self.validator = DataValidator()

    def create_batch(self, batch_name: str, rule_version: str, source_file: str = "", notes: str = "") -> Batch:
        batch = Batch(
            batch_name=batch_name,
            rule_version=rule_version,
            source_file=source_file,
            notes=notes,
            status="created"
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def import_sensor_readings(self, batch_id: int, file_path: str, skip_validation: bool = False) -> Tuple[bool, List[Dict], List[Dict]]:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            return False, [], [{"error": "批次不存在"}]

        df = self._read_file(file_path)
        if df is None:
            return False, [], [{"error": "无法读取文件"}]

        df, unmapped = self.field_mapper.map_columns(df, "sensor_readings")

        if not skip_validation:
            is_valid, errors = self.validator.validate(df, "sensor_readings")
            if not is_valid:
                error_dicts = [e.to_dict() for e in errors]
                return False, unmapped, error_dicts

        _, timezone_issues = self.validator.check_timezone(df)

        total_records = 0
        for idx, row in df.iterrows():
            reading_time = pd.to_datetime(row.get("reading_time")) if pd.notna(row.get("reading_time")) else None

            reading = SensorReading(
                batch_id=batch_id,
                raw_row_index=idx + 2,
                device_id=str(row.get("device_id", "")).strip(),
                reading_time=reading_time,
                water_pressure=float(row["water_pressure"]) if pd.notna(row.get("water_pressure")) else None,
                flow_rate=float(row["flow_rate"]) if pd.notna(row.get("flow_rate")) else None,
                temperature=float(row["temperature"]) if pd.notna(row.get("temperature")) else None,
                status=str(row.get("status", "")) if pd.notna(row.get("status")) else None,
                inspector=str(row.get("inspector", "")) if pd.notna(row.get("inspector")) else None,
                raw_data=json.dumps(row.to_dict(), ensure_ascii=False),
                time_zone=str(reading_time.tzinfo) if reading_time and reading_time.tzinfo else "Asia/Shanghai"
            )
            self.db.add(reading)
            total_records += 1

        batch.total_records = total_records
        batch.status = "data_imported"
        self.db.commit()

        return True, unmapped, timezone_issues

    def import_equipment_ledger(self, file_path: str, skip_validation: bool = False) -> Tuple[bool, int, List[Dict]]:
        df = self._read_file(file_path)
        if df is None:
            return False, 0, [{"error": "无法读取文件"}]

        df, _ = self.field_mapper.map_columns(df, "equipment_ledger")

        if not skip_validation:
            is_valid, errors = self.validator.validate(df, "equipment_ledger")
            if not is_valid:
                error_dicts = [e.to_dict() for e in errors]
                return False, 0, error_dicts

        count = 0
        for idx, row in df.iterrows():
            device_id = str(row.get("device_id", "")).strip()
            existing = self.db.query(EquipmentLedger).filter(EquipmentLedger.device_id == device_id).first()

            if existing:
                existing.device_name = row.get("device_name", existing.device_name)
                existing.location = row.get("location", existing.location)
                existing.install_date = pd.to_datetime(row.get("install_date")) if pd.notna(row.get("install_date")) else None
                existing.manufacturer = row.get("manufacturer")
                existing.model = row.get("model")
                existing.pressure_low_limit = float(row.get("pressure_low_limit", 0.1)) if pd.notna(row.get("pressure_low_limit")) else 0.1
                existing.pressure_high_limit = float(row.get("pressure_high_limit", 1.0)) if pd.notna(row.get("pressure_high_limit")) else 1.0
                existing.status = row.get("status", "active")
                existing.raw_data = json.dumps(row.to_dict(), ensure_ascii=False)
            else:
                ledger = EquipmentLedger(
                    device_id=device_id,
                    device_name=row.get("device_name", ""),
                    location=row.get("location", ""),
                    install_date=pd.to_datetime(row.get("install_date")) if pd.notna(row.get("install_date")) else None,
                    manufacturer=row.get("manufacturer"),
                    model=row.get("model"),
                    pressure_low_limit=float(row.get("pressure_low_limit", 0.1)) if pd.notna(row.get("pressure_low_limit")) else 0.1,
                    pressure_high_limit=float(row.get("pressure_high_limit", 1.0)) if pd.notna(row.get("pressure_high_limit")) else 1.0,
                    status=row.get("status", "active"),
                    raw_data=json.dumps(row.to_dict(), ensure_ascii=False)
                )
                self.db.add(ledger)
            count += 1

        self.db.commit()
        return True, count, []

    def import_inspection_shifts(self, batch_id: int, file_path: str) -> Tuple[bool, int, List[Dict]]:
        df = self._read_file(file_path)
        if df is None:
            return False, 0, [{"error": "无法读取文件"}]

        df, _ = self.field_mapper.map_columns(df, "inspection_shifts")

        is_valid, errors = self.validator.validate(df, "inspection_shifts")
        if not is_valid:
            error_dicts = [e.to_dict() for e in errors]
            return False, 0, error_dicts

        count = 0
        for idx, row in df.iterrows():
            shift = InspectionShift(
                batch_id=batch_id,
                shift_id=str(row.get("shift_id", "")),
                shift_date=pd.to_datetime(row.get("shift_date")) if pd.notna(row.get("shift_date")) else None,
                shift_type=row.get("shift_type"),
                inspector=row.get("inspector"),
                start_time=pd.to_datetime(row.get("start_time")) if pd.notna(row.get("start_time")) else None,
                end_time=pd.to_datetime(row.get("end_time")) if pd.notna(row.get("end_time")) else None,
                equipment_checked=row.get("equipment_checked"),
                raw_data=json.dumps(row.to_dict(), ensure_ascii=False)
            )
            self.db.add(shift)
            count += 1

        self.db.commit()
        return True, count, []

    def run_detection(self, batch_id: int, rule_config: Dict) -> Tuple[int, List[Anomaly]]:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            return 0, []

        detector = AnomalyDetector(self.db, rule_config)
        anomalies = detector.detect_all(batch_id)

        for anomaly in anomalies:
            self.db.add(anomaly)

        batch.anomaly_count = len(anomalies)
        batch.status = "detected"
        self.db.commit()

        return len(anomalies), anomalies

    def review_anomaly(self, anomaly_id: int, review_result: str, review_notes: str = "",
                       reviewed_by: str = "system") -> Optional[ReviewRecord]:
        anomaly = self.db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
        if not anomaly:
            return None

        anomaly.is_reviewed = True
        anomaly.review_result = review_result
        anomaly.review_notes = review_notes
        anomaly.reviewed_by = reviewed_by
        anomaly.reviewed_at = datetime.now()

        record = ReviewRecord(
            batch_id=anomaly.batch_id,
            anomaly_id=anomaly_id,
            review_result=review_result,
            review_notes=review_notes,
            reviewed_by=reviewed_by,
            action="review"
        )
        self.db.add(record)
        self.db.flush()

        batch = self.db.query(Batch).filter(Batch.id == anomaly.batch_id).first()
        if batch:
            reviewed_count = self.db.query(Anomaly).filter(
                Anomaly.batch_id == anomaly.batch_id,
                Anomaly.is_reviewed == True
            ).count()
            batch.reviewed_count = reviewed_count
            if reviewed_count >= batch.anomaly_count:
                batch.status = "reviewed"

        self.db.commit()
        return record

    def rollback_review(self, anomaly_id: int) -> Optional[ReviewRecord]:
        anomaly = self.db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
        if not anomaly or not anomaly.is_reviewed:
            return None

        anomaly.is_reviewed = False
        previous_result = anomaly.review_result
        anomaly.review_result = None
        anomaly.review_notes = None
        anomaly.reviewed_by = None
        anomaly.reviewed_at = None

        record = ReviewRecord(
            batch_id=anomaly.batch_id,
            anomaly_id=anomaly_id,
            review_result=f"rollback:{previous_result}",
            review_notes="回滚复核结果",
            reviewed_by="system",
            action="rollback"
        )
        self.db.add(record)
        self.db.flush()

        batch = self.db.query(Batch).filter(Batch.id == anomaly.batch_id).first()
        if batch:
            reviewed_count = self.db.query(Anomaly).filter(
                Anomaly.batch_id == anomaly.batch_id,
                Anomaly.is_reviewed == True
            ).count()
            batch.reviewed_count = reviewed_count
            batch.status = "detected"

        self.db.commit()
        return record

    def mark_as_rollback(self, anomaly_id: int, from_batch_id: int) -> Optional[Anomaly]:
        anomaly = self.db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
        if not anomaly:
            return None

        anomaly.is_rollback = True
        anomaly.rollback_from_batch_id = from_batch_id
        self.db.commit()
        return anomaly

    def get_batch(self, batch_id: int) -> Optional[Batch]:
        return self.db.query(Batch).filter(Batch.id == batch_id).first()

    def get_all_batches(self) -> List[Batch]:
        return self.db.query(Batch).order_by(Batch.import_time.desc()).all()

    def get_batch_anomalies(self, batch_id: int, reviewed: Optional[bool] = None) -> List[Anomaly]:
        query = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id)
        if reviewed is not None:
            query = query.filter(Anomaly.is_reviewed == reviewed)
        return query.order_by(Anomaly.detected_time.desc()).all()

    def get_batch_readings(self, batch_id: int) -> List[SensorReading]:
        return self.db.query(SensorReading).filter(SensorReading.batch_id == batch_id).all()

    def get_review_history(self, batch_id: Optional[int] = None) -> List[ReviewRecord]:
        query = self.db.query(ReviewRecord)
        if batch_id:
            query = query.filter(ReviewRecord.batch_id == batch_id)
        return query.order_by(ReviewRecord.reviewed_at.desc()).all()

    def get_equipment_ledger(self) -> List[EquipmentLedger]:
        return self.db.query(EquipmentLedger).all()

    def delete_batch(self, batch_id: int) -> bool:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            return False

        self.db.delete(batch)
        self.db.commit()
        return True

    def _read_file(self, file_path: str) -> Optional[pd.DataFrame]:
        if not os.path.exists(file_path):
            return None

        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".csv":
                return pd.read_csv(file_path, encoding="utf-8-sig")
            elif ext in [".xlsx", ".xls"]:
                return pd.read_excel(file_path)
            else:
                return None
        except Exception as e:
            print(f"读取文件错误: {e}")
            return None

    def get_anomaly_summary(self, batch_id: int) -> Dict:
        anomalies = self.get_batch_anomalies(batch_id)
        summary = {}
        for a in anomalies:
            key = a.anomaly_code
            if key not in summary:
                summary[key] = {
                    "name": a.anomaly_type,
                    "count": 0,
                    "reviewed": 0,
                    "confirmed": 0,
                    "false_positive": 0
                }
            summary[key]["count"] += 1
            if a.is_reviewed:
                summary[key]["reviewed"] += 1
                if a.review_result == "confirmed":
                    summary[key]["confirmed"] += 1
                elif a.review_result == "false_positive":
                    summary[key]["false_positive"] += 1
        return summary
