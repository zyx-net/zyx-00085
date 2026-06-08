import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import SensorReading, EquipmentLedger, Anomaly, Batch


class AnomalyDetector:
    def __init__(self, db_session: Session, rule_config: Dict):
        self.db = db_session
        self.rule_config = rule_config
        self.rules = rule_config.get("rules", {})
        self.version = rule_config.get("version", "unknown")

    def detect_all(self, batch_id: int) -> List[Anomaly]:
        anomalies = []
        readings_df = self._load_readings(batch_id)
        equipment_df = self._load_equipment()

        if self._is_rule_enabled("unregistered_device"):
            anomalies.extend(self.detect_unregistered_device(readings_df, equipment_df, batch_id))

        if self._is_rule_enabled("same_time_different_reading"):
            anomalies.extend(self.detect_same_time_different_reading(readings_df, batch_id))

        if self._is_rule_enabled("duplicate_report"):
            anomalies.extend(self.detect_duplicate_report(readings_df, batch_id))

        if self._is_rule_enabled("pressure_sudden_drop"):
            anomalies.extend(self.detect_pressure_sudden_drop(readings_df, batch_id))

        if self._is_rule_enabled("reading_backward"):
            anomalies.extend(self.detect_reading_backward(readings_df, batch_id))

        if self._is_rule_enabled("long_time_offline"):
            anomalies.extend(self.detect_long_time_offline(readings_df, batch_id))

        if self._is_rule_enabled("pressure_out_of_range"):
            anomalies.extend(self.detect_pressure_out_of_range(readings_df, equipment_df, batch_id))

        return anomalies

    def _is_rule_enabled(self, rule_name: str) -> bool:
        return self.rules.get(rule_name, {}).get("enabled", False)

    def _load_readings(self, batch_id: int) -> pd.DataFrame:
        readings = self.db.query(SensorReading).filter(
            SensorReading.batch_id == batch_id
        ).order_by(SensorReading.device_id, SensorReading.reading_time).all()

        data = []
        for r in readings:
            data.append({
                "id": r.id,
                "batch_id": r.batch_id,
                "device_id": r.device_id,
                "reading_time": r.reading_time,
                "water_pressure": r.water_pressure,
                "flow_rate": r.flow_rate,
                "temperature": r.temperature,
                "raw_row_index": r.raw_row_index
            })
        return pd.DataFrame(data)

    def _load_equipment(self) -> pd.DataFrame:
        equipment = self.db.query(EquipmentLedger).all()
        data = []
        for e in equipment:
            data.append({
                "device_id": e.device_id,
                "device_name": e.device_name,
                "pressure_low_limit": e.pressure_low_limit,
                "pressure_high_limit": e.pressure_high_limit,
                "status": e.status
            })
        return pd.DataFrame(data)

    def detect_unregistered_device(self, readings_df: pd.DataFrame, equipment_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty or equipment_df.empty:
            return anomalies

        rule = self.rules["unregistered_device"]
        registered_devices = set(equipment_df["device_id"].unique())
        unregistered = readings_df[~readings_df["device_id"].isin(registered_devices)]

        for _, row in unregistered.iterrows():
            anomaly = Anomaly(
                batch_id=batch_id,
                reading_id=row["id"],
                anomaly_type=rule["name"],
                anomaly_code="UNREGISTERED_DEVICE",
                severity="critical",
                description=f"设备 {row['device_id']} 未在设备台账中登记",
                device_id=row["device_id"],
                reading_time=row["reading_time"]
            )
            anomalies.append(anomaly)
        return anomalies

    def detect_same_time_different_reading(self, readings_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty:
            return anomalies

        rule = self.rules["same_time_different_reading"]

        grouped = readings_df.groupby(["device_id", "reading_time"])
        for (device_id, reading_time), group in grouped:
            if len(group) > 1:
                pressure_values = group["water_pressure"].dropna().unique()
                if len(pressure_values) > 1:
                    for _, row in group.iterrows():
                        anomaly = Anomaly(
                            batch_id=batch_id,
                            reading_id=row["id"],
                            anomaly_type=rule["name"],
                            anomaly_code="SAME_TIME_DIFFERENT_READING",
                            severity="high",
                            description=f"设备 {device_id} 在 {reading_time} 时间点出现不同读数: {pressure_values}",
                            device_id=device_id,
                            reading_time=reading_time,
                            expected_value=pressure_values[0],
                            actual_value=pressure_values[1]
                        )
                        anomalies.append(anomaly)
        return anomalies

    def detect_duplicate_report(self, readings_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty:
            return anomalies

        rule = self.rules["duplicate_report"]
        time_window = timedelta(seconds=rule["time_window_seconds"])

        for device_id, group in readings_df.groupby("device_id"):
            group = group.sort_values("reading_time")
            times = group["reading_time"].tolist()
            ids = group["id"].tolist()

            for i in range(len(times) - 1):
                if times[i + 1] - times[i] <= time_window:
                    row = group.iloc[i + 1]
                    anomaly = Anomaly(
                        batch_id=batch_id,
                        reading_id=ids[i + 1],
                        anomaly_type=rule["name"],
                        anomaly_code="DUPLICATE_REPORT",
                        severity="low",
                        description=f"设备 {device_id} 在 {rule['time_window_seconds']} 秒内重复上报",
                        device_id=device_id,
                        reading_time=row["reading_time"]
                    )
                    anomalies.append(anomaly)
        return anomalies

    def detect_pressure_sudden_drop(self, readings_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty:
            return anomalies

        rule = self.rules["pressure_sudden_drop"]
        threshold = rule["threshold"]
        time_window = timedelta(minutes=rule["time_window_minutes"])

        for device_id, group in readings_df.groupby("device_id"):
            group = group.sort_values("reading_time")
            pressures = group["water_pressure"].tolist()
            times = group["reading_time"].tolist()
            ids = group["id"].tolist()

            for i in range(1, len(pressures)):
                if pd.isna(pressures[i]) or pd.isna(pressures[i - 1]):
                    continue
                pressure_drop = pressures[i - 1] - pressures[i]
                time_diff = times[i] - times[i - 1]

                if pressure_drop >= threshold and time_diff <= time_window:
                    row = group.iloc[i]
                    anomaly = Anomaly(
                        batch_id=batch_id,
                        reading_id=ids[i],
                        anomaly_type=rule["name"],
                        anomaly_code="PRESSURE_SUDDEN_DROP",
                        severity="high",
                        description=f"设备 {device_id} 在 {time_diff.total_seconds() / 60:.0f} 分钟内水压下降 {pressure_drop:.2f}MPa",
                        device_id=device_id,
                        reading_time=row["reading_time"],
                        expected_value=pressures[i - 1],
                        actual_value=pressures[i]
                    )
                    anomalies.append(anomaly)
        return anomalies

    def detect_reading_backward(self, readings_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty:
            return anomalies

        rule = self.rules["reading_backward"]
        threshold = rule.get("threshold", 10.0)

        for device_id, group in readings_df.groupby("device_id"):
            group = group.sort_values("reading_time")
            flow_rates = group["flow_rate"].tolist()
            ids = group["id"].tolist()
            times = group["reading_time"].tolist()

            for i in range(1, len(flow_rates)):
                if pd.isna(flow_rates[i]) or pd.isna(flow_rates[i - 1]):
                    continue
                drop_amount = flow_rates[i - 1] - flow_rates[i]
                if drop_amount >= threshold:
                    row = group.iloc[i]
                    anomaly = Anomaly(
                        batch_id=batch_id,
                        reading_id=ids[i],
                        anomaly_type=rule["name"],
                        anomaly_code="READING_BACKWARD",
                        severity="medium",
                        description=f"设备 {device_id} 流量读数出现倒退: {flow_rates[i-1]} -> {flow_rates[i]} (下降 {drop_amount:.1f}m³/h)",
                        device_id=device_id,
                        reading_time=times[i],
                        expected_value=flow_rates[i - 1],
                        actual_value=flow_rates[i]
                    )
                    anomalies.append(anomaly)
        return anomalies

    def detect_long_time_offline(self, readings_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty:
            return anomalies

        rule = self.rules["long_time_offline"]
        threshold = timedelta(hours=rule["threshold_hours"])

        for device_id, group in readings_df.groupby("device_id"):
            group = group.sort_values("reading_time")
            times = group["reading_time"].tolist()
            ids = group["id"].tolist()

            for i in range(1, len(times)):
                time_diff = times[i] - times[i - 1]
                if time_diff >= threshold:
                    row = group.iloc[i]
                    anomaly = Anomaly(
                        batch_id=batch_id,
                        reading_id=ids[i],
                        anomaly_type=rule["name"],
                        anomaly_code="LONG_TIME_OFFLINE",
                        severity="medium",
                        description=f"设备 {device_id} 离线时间长达 {time_diff.total_seconds() / 3600:.1f} 小时",
                        device_id=device_id,
                        reading_time=row["reading_time"]
                    )
                    anomalies.append(anomaly)
        return anomalies

    def detect_pressure_out_of_range(self, readings_df: pd.DataFrame, equipment_df: pd.DataFrame, batch_id: int) -> List[Anomaly]:
        anomalies = []
        if readings_df.empty or equipment_df.empty:
            return anomalies

        rule = self.rules["pressure_out_of_range"]

        merged = readings_df.merge(equipment_df, on="device_id", how="left")

        for _, row in merged.iterrows():
            if pd.isna(row["water_pressure"]) or pd.isna(row["pressure_low_limit"]) or pd.isna(row["pressure_high_limit"]):
                continue

            pressure = row["water_pressure"]
            low = row["pressure_low_limit"]
            high = row["pressure_high_limit"]

            if pressure < low or pressure > high:
                anomaly = Anomaly(
                    batch_id=batch_id,
                    reading_id=row["id"],
                    anomaly_type=rule["name"],
                    anomaly_code="PRESSURE_OUT_OF_RANGE",
                    severity="high",
                    description=f"设备 {row['device_id']} 水压 {pressure} 超出范围 [{low}, {high}]",
                    device_id=row["device_id"],
                    reading_time=row["reading_time"],
                    expected_value=(low + high) / 2,
                    actual_value=pressure
                )
                anomalies.append(anomaly)
        return anomalies
