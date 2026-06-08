import json
import os
import pandas as pd
from typing import Dict, List, Tuple, Optional
from datetime import datetime


class ValidationError:
    def __init__(self, error_type: str, column: str, row: int, message: str):
        self.error_type = error_type
        self.column = column
        self.row = row
        self.message = message

    def __str__(self):
        return f"[{self.error_type}] 行{self.row} 列'{self.column}': {self.message}"

    def to_dict(self):
        return {
            "error_type": self.error_type,
            "column": self.column,
            "row": self.row,
            "message": self.message
        }


class DataValidator:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config",
                "validation_rules.json"
            )
        self.config_path = config_path
        self.rules = self._load_rules()

    def _load_rules(self) -> Dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def validate(self, df: pd.DataFrame, data_type: str) -> Tuple[bool, List[ValidationError]]:
        rules = self.rules.get(data_type, {})
        errors = []

        errors.extend(self._check_required_columns(df, rules.get("required_columns", [])))
        errors.extend(self._check_unique_columns(df, rules.get("unique_columns", [])))
        errors.extend(self._check_value_ranges(df, rules.get("value_ranges", {})))
        errors.extend(self._check_data_types(df, data_type))

        return len(errors) == 0, errors

    def _check_required_columns(self, df: pd.DataFrame, required_columns: List[str]) -> List[ValidationError]:
        errors = []
        missing_columns = [col for col in required_columns if col not in df.columns]
        for col in missing_columns:
            errors.append(ValidationError(
                "missing_column",
                col,
                0,
                f"缺少必填列: {col}"
            ))
        return errors

    def _check_unique_columns(self, df: pd.DataFrame, unique_columns: List[str]) -> List[ValidationError]:
        errors = []
        for col in unique_columns:
            if col in df.columns:
                mask = df.duplicated(subset=[col], keep=False)
                for pos, idx in enumerate(df.index[mask]):
                    row = df.loc[idx]
                    row_num = int(idx) + 2 if isinstance(idx, (int, float)) and not isinstance(idx, bool) else pos + 2
                    errors.append(ValidationError(
                        "duplicate_value",
                        col,
                        row_num,
                        f"重复值: {row[col]}"
                    ))
        return errors

    def _check_value_ranges(self, df: pd.DataFrame, value_ranges: Dict) -> List[ValidationError]:
        errors = []
        for col, range_info in value_ranges.items():
            if col in df.columns:
                min_val = range_info.get("min")
                max_val = range_info.get("max")
                for pos, (idx, value) in enumerate(df[col].items()):
                    if pd.isna(value):
                        continue
                    row_num = int(idx) + 2 if isinstance(idx, (int, float)) and not isinstance(idx, bool) else pos + 2
                    try:
                        num_value = float(value)
                        if min_val is not None and num_value < min_val:
                            errors.append(ValidationError(
                                "value_out_of_range",
                                col,
                                row_num,
                                f"值 {num_value} 小于最小值 {min_val}"
                            ))
                        if max_val is not None and num_value > max_val:
                            errors.append(ValidationError(
                                "value_out_of_range",
                                col,
                                row_num,
                                f"值 {num_value} 大于最大值 {max_val}"
                            ))
                    except (ValueError, TypeError):
                        errors.append(ValidationError(
                            "invalid_type",
                            col,
                            row_num,
                            f"无法将值 {value} 转换为数字"
                        ))
        return errors

    def _check_data_types(self, df: pd.DataFrame, data_type: str) -> List[ValidationError]:
        errors = []

        if data_type == "sensor_readings":
            if "reading_time" in df.columns:
                for pos, (idx, value) in enumerate(df["reading_time"].items()):
                    row_num = int(idx) + 2 if isinstance(idx, (int, float)) and not isinstance(idx, bool) else pos + 2
                    if pd.isna(value):
                        errors.append(ValidationError(
                            "invalid_time",
                            "reading_time",
                            row_num,
                            "时间值为空"
                        ))
                    else:
                        try:
                            pd.to_datetime(value)
                        except Exception:
                            errors.append(ValidationError(
                                "invalid_time",
                                "reading_time",
                                row_num,
                                f"无效的时间格式: {value}"
                            ))

        if data_type == "inspection_shifts":
            if "shift_date" in df.columns:
                for pos, (idx, value) in enumerate(df["shift_date"].items()):
                    row_num = int(idx) + 2 if isinstance(idx, (int, float)) and not isinstance(idx, bool) else pos + 2
                    if pd.isna(value):
                        errors.append(ValidationError(
                            "invalid_date",
                            "shift_date",
                            row_num,
                            "日期值为空"
                        ))

        return errors

    def check_timezone(self, df: pd.DataFrame, time_col: str = "reading_time") -> Tuple[bool, List[Dict]]:
        """检查时区异常"""
        issues = []
        is_valid = True

        if time_col not in df.columns:
            return True, issues

        for pos, (idx, value) in enumerate(df[time_col].items()):
            if pd.isna(value):
                continue
            row_num = int(idx) + 2 if isinstance(idx, (int, float)) and not isinstance(idx, bool) else pos + 2
            try:
                dt = pd.to_datetime(value)
                if dt.tzinfo is not None and str(dt.tzinfo) not in ["Asia/Shanghai", "UTC+8", "China Standard Time"]:
                    is_valid = False
                    issues.append({
                        "row": row_num,
                        "value": str(value),
                        "timezone": str(dt.tzinfo),
                        "message": f"非预期时区: {dt.tzinfo}"
                    })
                elif dt.year < 2020 or dt.year > 2030:
                    is_valid = False
                    issues.append({
                        "row": row_num,
                        "value": str(value),
                        "year": dt.year,
                        "message": f"时间年份异常: {dt.year}"
                    })
            except Exception:
                pass

        return is_valid, issues
