import json
import os
import pandas as pd
from typing import Dict, List, Tuple, Optional


class FieldMapper:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config",
                "field_mapping.json"
            )
        self.config_path = config_path
        self.mappings = self._load_mappings()

    def _load_mappings(self) -> Dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_mapping(self, data_type: str) -> Dict[str, str]:
        return self.mappings.get(data_type, {})

    def get_reverse_mapping(self, data_type: str) -> Dict[str, str]:
        mapping = self.get_mapping(data_type)
        return {v: k for k, v in mapping.items()}

    def map_columns(self, df: pd.DataFrame, data_type: str) -> Tuple[pd.DataFrame, List[str]]:
        reverse_mapping = self.get_reverse_mapping(data_type)
        original_columns = list(df.columns)
        new_columns = []
        unmapped_columns = []

        for col in original_columns:
            if col in reverse_mapping:
                new_columns.append(reverse_mapping[col])
            elif col in self.get_mapping(data_type):
                new_columns.append(col)
            else:
                new_columns.append(col)
                unmapped_columns.append(col)

        df = df.copy()
        df.columns = new_columns
        return df, unmapped_columns

    def map_to_display(self, data: Dict, data_type: str) -> Dict:
        mapping = self.get_mapping(data_type)
        result = {}
        for key, value in data.items():
            display_key = mapping.get(key, key)
            result[display_key] = value
        return result

    def update_mapping(self, data_type: str, field_name: str, display_name: str):
        if data_type not in self.mappings:
            self.mappings[data_type] = {}
        self.mappings[data_type][field_name] = display_name
        self._save_mappings()

    def _save_mappings(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.mappings, f, ensure_ascii=False, indent=2)
