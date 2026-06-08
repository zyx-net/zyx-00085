from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class Batch(Base):
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_name = Column(String(200), nullable=False)
    rule_version = Column(String(50), nullable=False)
    import_time = Column(DateTime, default=datetime.now)
    status = Column(String(50), default="processing")
    total_records = Column(Integer, default=0)
    anomaly_count = Column(Integer, default=0)
    reviewed_count = Column(Integer, default=0)
    source_file = Column(String(500))
    notes = Column(Text)

    anomalies = relationship("Anomaly", back_populates="batch", cascade="all, delete-orphan")
    sensor_readings = relationship("SensorReading", back_populates="batch", cascade="all, delete-orphan")
    review_records = relationship("ReviewRecord", back_populates="batch", cascade="all, delete-orphan")


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    raw_row_index = Column(Integer)
    device_id = Column(String(100), nullable=False)
    reading_time = Column(DateTime, nullable=False)
    water_pressure = Column(Float)
    flow_rate = Column(Float)
    temperature = Column(Float)
    status = Column(String(50))
    inspector = Column(String(100))
    raw_data = Column(Text)
    time_zone = Column(String(50), default="Asia/Shanghai")

    batch = relationship("Batch", back_populates="sensor_readings")
    anomalies = relationship("Anomaly", back_populates="reading")


class InspectionShift(Base):
    __tablename__ = "inspection_shifts"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"))
    shift_id = Column(String(100), nullable=False, unique=True)
    shift_date = Column(DateTime, nullable=False)
    shift_type = Column(String(50))
    inspector = Column(String(100))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    equipment_checked = Column(String(500))
    raw_data = Column(Text)


class EquipmentLedger(Base):
    __tablename__ = "equipment_ledger"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(100), nullable=False, unique=True)
    device_name = Column(String(200), nullable=False)
    location = Column(String(200), nullable=False)
    install_date = Column(DateTime)
    manufacturer = Column(String(200))
    model = Column(String(200))
    pressure_low_limit = Column(Float, default=0.1)
    pressure_high_limit = Column(Float, default=1.0)
    status = Column(String(50), default="active")
    raw_data = Column(Text)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    reading_id = Column(Integer, ForeignKey("sensor_readings.id"))
    anomaly_type = Column(String(100), nullable=False)
    anomaly_code = Column(String(50), nullable=False)
    severity = Column(String(50), default="warning")
    description = Column(Text)
    device_id = Column(String(100))
    reading_time = Column(DateTime)
    expected_value = Column(Float)
    actual_value = Column(Float)
    detected_time = Column(DateTime, default=datetime.now)
    is_reviewed = Column(Boolean, default=False)
    review_result = Column(String(50))
    review_notes = Column(Text)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    is_rollback = Column(Boolean, default=False)
    rollback_from_batch_id = Column(Integer)

    batch = relationship("Batch", back_populates="anomalies")
    reading = relationship("SensorReading", back_populates="anomalies")
    review_records = relationship("ReviewRecord", back_populates="anomaly", cascade="all, delete-orphan")


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=False)
    review_result = Column(String(50), nullable=False)
    review_notes = Column(Text)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime, default=datetime.now)
    action = Column(String(50), default="review")

    batch = relationship("Batch", back_populates="review_records")
    anomaly = relationship("Anomaly", back_populates="review_records")


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id = Column(Integer, primary_key=True, index=True)
    version = Column(String(50), nullable=False, unique=True)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    based_on = Column(String(50))
    rule_config = Column(Text, nullable=False)
    is_active = Column(Boolean, default=False)
