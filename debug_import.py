#!/usr/bin/env python3
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pump_inspection.field_mapper import FieldMapper
from pump_inspection.validator import DataValidator

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")

def test_inspection_shifts():
    file_path = os.path.join(SAMPLE_DATA_DIR, "inspection_shifts.csv")
    print(f"测试文件: {file_path}")
    print(f"文件存在: {os.path.exists(file_path)}")
    
    df = pd.read_csv(file_path, encoding="utf-8-sig")
    print(f"\n原始列名: {list(df.columns)}")
    print(f"原始数据行数: {len(df)}")
    print(f"\n原始数据:")
    print(df)
    
    mapper = FieldMapper()
    df_mapped, unmapped = mapper.map_columns(df, "inspection_shifts")
    print(f"\n映射后列名: {list(df_mapped.columns)}")
    print(f"未映射列: {unmapped}")
    
    print(f"\n映射后数据:")
    print(df_mapped)
    
    validator = DataValidator()
    is_valid, errors = validator.validate(df_mapped, "inspection_shifts")
    print(f"\n校验结果: {'通过' if is_valid else '失败'}")
    if errors:
        print("错误:")
        for e in errors:
            print(f"  {e}")

if __name__ == "__main__":
    test_inspection_shifts()
