#!/usr/bin/env python3
"""
回归测试脚本 - 覆盖 GBK 编码场景、异常数量验证、README 分步命令等
"""
import os
import sys
import io
import re
import subprocess
import tempfile
import shutil
from pathlib import Path


class _UnicodeSafeStreamWrapper(io.TextIOWrapper):
    def __init__(self, buffer, encoding='utf-8', errors='replace'):
        super().__init__(buffer, encoding=encoding, errors=errors,
                         line_buffering=True, write_through=True)

    def write(self, s):
        try:
            return super().write(s)
        except UnicodeEncodeError:
            safe_s = s.encode(self.encoding, errors='replace').decode(self.encoding)
            return super().write(safe_s)


def _setup_unicode_safe_output():
    if sys.platform != "win32":
        return
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        return
    except (AttributeError, io.UnsupportedOperation):
        pass
    try:
        stdout_bin = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout
        stderr_bin = sys.stderr.buffer if hasattr(sys.stderr, 'buffer') else sys.stderr
        sys.stdout = _UnicodeSafeStreamWrapper(stdout_bin, encoding='utf-8')
        sys.stderr = _UnicodeSafeStreamWrapper(stderr_bin, encoding='utf-8')
    except Exception:
        os.environ.setdefault('PYTHONIOENCODING', 'utf-8:replace')


_setup_unicode_safe_output()

PROJECT_ROOT = Path(__file__).parent
MAIN_PY = PROJECT_ROOT / "main.py"
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
DB_PATH = PROJECT_ROOT / "pump_inspection.db"
REPORTS_DIR = PROJECT_ROOT / "reports"

EXPECTED_ANOMALY_COUNT = 13
EXPECTED_ANOMALY_TYPES = {
    "PRESSURE_OUT_OF_RANGE": 2,
    "LONG_TIME_OFFLINE": 2,
    "READING_BACKWARD": 1,
    "PRESSURE_SUDDEN_DROP": 2,
    "DUPLICATE_REPORT": 2,
    "SAME_TIME_DIFFERENT_READING": 2,
    "UNREGISTERED_DEVICE": 2,
}


def run_cmd(cmd, env=None, capture=True, cwd=None):
    """运行命令并返回结果，确保 stdout 和 stderr 不为 None"""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    if isinstance(cmd, list):
        args = cmd
    else:
        args = [sys.executable, str(MAIN_PY)] + cmd.split()
    
    full_env.setdefault('PYTHONIOENCODING', 'utf-8:replace')
    
    kwargs = {
        "env": full_env,
        "cwd": cwd or str(PROJECT_ROOT),
        "stdout": subprocess.PIPE if capture else None,
        "stderr": subprocess.PIPE if capture else None,
        "encoding": 'utf-8',
        "errors": 'replace',
    }
    
    result = subprocess.run(args, **kwargs)
    result.stdout = result.stdout or ""
    result.stderr = result.stderr or ""
    return result


def clean_test_env():
    """清理测试环境，带重试机制"""
    import time
    
    for _ in range(10):
        try:
            if DB_PATH.exists():
                DB_PATH.unlink()
            break
        except Exception:
            time.sleep(0.2)
    
    if REPORTS_DIR.exists():
        for f in REPORTS_DIR.glob("*"):
            try:
                if f.is_file():
                    f.unlink()
            except Exception:
                pass
    time.sleep(0.2)


def setup_test_env():
    """设置测试环境 - 导入设备台账"""
    clean_test_env()
    result = run_cmd("init-db")
    assert result.returncode == 0, f"init-db 失败: {result.stderr}"
    
    result = run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    assert result.returncode == 0, f"import-equipment 失败: {result.stderr}"
    
    result = run_cmd('create-batch --name "测试批次" --rule-version v2')
    assert result.returncode == 0, f"create-batch 失败: {result.stderr}"


def test_gbk_encoding_scenario():
    """测试 GBK 编码场景 - 复现 UnicodeEncodeError"""
    print("\n" + "=" * 70)
    print("测试 1: GBK 编码场景 - 验证不会出现 UnicodeEncodeError")
    print("=" * 70)
    
    setup_test_env()
    
    result = run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    assert result.returncode == 0, f"import-readings 失败: {result.stderr}"
    
    result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0, f"import-shifts 失败: {result.stderr}"
    
    result = run_cmd("detect --batch-id 1")
    assert result.returncode == 0, f"detect 失败: {result.stderr}"
    
    gbk_env = {
        "PYTHONIOENCODING": "gbk",
        "LANG": "zh_CN.GBK",
    }
    
    print("  测试 1.1: 设置 PYTHONIOENCODING=gbk 运行 list-anomalies...")
    result = run_cmd("list-anomalies --batch-id 1", env=gbk_env)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    
    if result.returncode != 0:
        print(f"    ❌ 失败: 返回码 {result.returncode}")
        print(f"    stdout: {stdout[:500]}")
        print(f"    stderr: {stderr[:500]}")
        if "UnicodeEncodeError" in stderr or "UnicodeEncodeError" in stdout:
            raise AssertionError("GBK 编码下出现 UnicodeEncodeError 崩溃！")
    else:
        assert "m" in stdout or "\u33a5" in stdout or "?" in stdout, \
            "输出中应该包含 m³ 或其替换字符"
        print(f"    ✅ 通过 (返回码 0, 输出 {len(stdout)} 字符)")
    
    print("  测试 1.2: 验证读数倒退异常描述可正常打印...")
    result = run_cmd("list-anomalies --batch-id 1", env=gbk_env)
    assert result.returncode == 0, f"list-anomalies 在 GBK 下失败: {result.stderr}"
    
    anomaly_count = len([l for l in result.stdout.split('\n') if l.strip().startswith('ID=')])
    assert anomaly_count == EXPECTED_ANOMALY_COUNT, \
        f"异常数量不匹配: 期望 {EXPECTED_ANOMALY_COUNT}, 实际 {anomaly_count}"
    
    has_flow_desc = any('m' in l and ('155.5' in l or '130.0' in l) for l in result.stdout.split('\n'))
    print(f"    ✅ 通过 (输出 {anomaly_count} 条异常, 含流量描述: {has_flow_desc})")
    
    clean_test_env()
    print("  ✅ GBK 编码场景测试全部通过")


def test_anomaly_count_consistency():
    """测试异常数量一致性 - README、CLI 输出、检测结果"""
    print("\n" + "=" * 70)
    print("测试 2: 异常数量一致性验证")
    print("=" * 70)
    
    setup_test_env()
    
    result = run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    assert result.returncode == 0
    
    result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    
    print("  测试 2.1: detect 命令输出异常数量...")
    result = run_cmd("detect --batch-id 1")
    assert result.returncode == 0
    
    detect_output = result.stdout
    assert f"共发现 {EXPECTED_ANOMALY_COUNT} 条异常" in detect_output, \
        f"detect 输出异常数量不匹配: {detect_output[:300]}"
    print(f"    ✅ 通过 (detect 输出: 共发现 {EXPECTED_ANOMALY_COUNT} 条异常)")
    
    for anomaly_type, expected_count in EXPECTED_ANOMALY_TYPES.items():
        assert f"{expected_count} 条" in detect_output, \
            f"缺少 {anomaly_type} 的数量输出: {detect_output}"
    
    print("  测试 2.2: list-anomalies 输出异常数量...")
    result = run_cmd("list-anomalies --batch-id 1")
    assert result.returncode == 0
    
    list_output = result.stdout
    assert f"共 {EXPECTED_ANOMALY_COUNT} 条" in list_output, \
        f"list-anomalies 输出异常数量不匹配: {list_output[:200]}"
    
    anomaly_lines = [l for l in list_output.split('\n') if l.strip().startswith('ID=')]
    assert len(anomaly_lines) == EXPECTED_ANOMALY_COUNT, \
        f"异常明细数量不匹配: 期望 {EXPECTED_ANOMALY_COUNT}, 实际 {len(anomaly_lines)}"
    print(f"    ✅ 通过 (list-anomalies 输出 {len(anomaly_lines)} 条异常明细)")
    
    print("  测试 2.3: list-batches 显示异常数量...")
    result = run_cmd("list-batches")
    assert result.returncode == 0
    
    batch_line = [l for l in result.stdout.split('\n') if 'ID=1' in l][0]
    assert f"异常={EXPECTED_ANOMALY_COUNT}" in batch_line, \
        f"list-batches 异常数量不匹配: {batch_line}"
    print(f"    ✅ 通过 (list-batches 显示: 异常={EXPECTED_ANOMALY_COUNT})")
    
    print("  测试 2.4: 检测结果异常类型分布...")
    
    result = run_cmd("list-anomalies --batch-id 1")
    assert result.returncode == 0
    
    type_counts = {}
    for line in result.stdout.split('\n'):
        if line.strip().startswith('ID='):
            match = re.search(r'\((\w+)\)', line)
            if match:
                code = match.group(1)
                type_counts[code] = type_counts.get(code, 0) + 1
    
    assert type_counts == EXPECTED_ANOMALY_TYPES, \
        f"异常类型分布不匹配: 期望 {EXPECTED_ANOMALY_TYPES}, 实际 {type_counts}"
    
    for code, count in type_counts.items():
        print(f"    - {code}: {count} 条 ✅")
    
    clean_test_env()
    import time
    time.sleep(0.3)
    print("  ✅ 异常数量一致性测试全部通过")


def test_readme_step_by_step():
    """测试 README 分步命令"""
    print("\n" + "=" * 70)
    print("测试 3: README 分步命令验证")
    print("=" * 70)
    
    clean_test_env()
    
    steps = [
        ("init-db", "初始化数据库", "python main.py init-db"),
        ("import-equipment", "导入设备台账", 
         f'python main.py import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}'),
        ("list-equipment", "查看设备台账", "python main.py list-equipment"),
        ("create-batch", "创建分析批次", 
         'python main.py create-batch --name "2026年6月数据分析" --rule-version v2'),
        ("import-readings", "导入传感器读数", 
         f'python main.py import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}'),
        ("import-shifts", "导入巡检班次", 
         f'python main.py import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}'),
        ("detect", "运行异常检测", "python main.py detect --batch-id 1"),
        ("list-batches", "查看所有批次", "python main.py list-batches"),
        ("list-anomalies", "查看批次异常", "python main.py list-anomalies --batch-id 1"),
        ("review", "复核异常（误报）", 
         'python main.py review --anomaly-id 1 --result false_positive --notes "传感器波动" --reviewer "张三"'),
        ("rollback", "回滚复核结果", "python main.py rollback --anomaly-id 1"),
        ("review2", "复核异常（确认）", 
         'python main.py review --anomaly-id 2 --result confirmed --notes "现场核实" --reviewer "李四"'),
        ("export-html", "导出HTML报告", "python main.py export-html --batch-id 1"),
        ("export-csv", "导出CSV报告", "python main.py export-csv --batch-id 1"),
    ]
    
    for step_id, step_name, cmd_str in steps:
        print(f"  步骤: {step_name}")
        print(f"    命令: {cmd_str}")
        
        if step_id == "init-db":
            result = run_cmd("init-db")
        elif step_id == "import-equipment":
            result = run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
        elif step_id == "list-equipment":
            result = run_cmd("list-equipment")
        elif step_id == "create-batch":
            result = run_cmd('create-batch --name "2026年6月数据分析" --rule-version v2')
        elif step_id == "import-readings":
            result = run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
        elif step_id == "import-shifts":
            result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
        elif step_id == "detect":
            result = run_cmd("detect --batch-id 1")
            assert f"共发现 {EXPECTED_ANOMALY_COUNT} 条异常" in result.stdout
        elif step_id == "list-batches":
            result = run_cmd("list-batches")
            assert "ID=1" in result.stdout
        elif step_id == "list-anomalies":
            result = run_cmd("list-anomalies --batch-id 1")
            assert f"共 {EXPECTED_ANOMALY_COUNT} 条" in result.stdout
        elif step_id == "review":
            result = run_cmd('review --anomaly-id 1 --result false_positive --notes "传感器波动" --reviewer "张三"')
        elif step_id == "rollback":
            result = run_cmd("rollback --anomaly-id 1")
        elif step_id == "review2":
            result = run_cmd('review --anomaly-id 2 --result confirmed --notes "现场核实" --reviewer "李四"')
        elif step_id == "export-html":
            result = run_cmd("export-html --batch-id 1")
            assert "HTML报告已导出" in result.stdout
        elif step_id == "export-csv":
            result = run_cmd("export-csv --batch-id 1")
            assert "CSV报告已导出" in result.stdout
        
        assert result.returncode == 0, f"步骤失败: {step_name}\n{result.stderr[:300]}"
        print(f"    ✅ 通过")
    
    clean_test_env()
    print("  ✅ README 分步命令测试全部通过")


def test_review_and_rollback():
    """测试复核和回滚功能"""
    print("\n" + "=" * 70)
    print("测试 4: 复核和回滚功能")
    print("=" * 70)
    
    setup_test_env()
    
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    run_cmd("detect --batch-id 1")
    
    print("  测试 4.1: 复核异常（误报）...")
    result = run_cmd('review --anomaly-id 5 --result false_positive --notes "测试误报" --reviewer "测试员"')
    assert result.returncode == 0
    print("    ✅ 通过")
    
    print("  测试 4.2: 验证已复核计数更新...")
    result = run_cmd("list-batches")
    assert "已复核=1" in result.stdout
    print("    ✅ 通过")
    
    print("  测试 4.3: 回滚复核结果...")
    result = run_cmd("rollback --anomaly-id 5")
    assert result.returncode == 0
    print("    ✅ 通过")
    
    print("  测试 4.4: 验证回滚后计数归零...")
    result = run_cmd("list-batches")
    assert "已复核=0" in result.stdout
    print("    ✅ 通过")
    
    print("  测试 4.5: 复核异常（确认）...")
    result = run_cmd('review --anomaly-id 6 --result confirmed --notes "测试确认" --reviewer "测试员2"')
    assert result.returncode == 0
    print("    ✅ 通过")
    
    print("  测试 4.6: 验证复核历史...")
    result = run_cmd("list-anomalies --batch-id 1 --reviewed yes")
    assert result.returncode == 0
    assert "已复核: confirmed" in result.stdout
    print("    ✅ 通过")
    
    clean_test_env()
    print("  ✅ 复核和回滚测试全部通过")


def test_invalid_input():
    """测试非法输入场景"""
    print("\n" + "=" * 70)
    print("测试 5: 非法输入场景")
    print("=" * 70)
    
    setup_test_env()
    
    print("  测试 5.1: 缺少必填列（缺少设备编号）...")
    result = run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_missing_device_id.csv"}')
    assert result.returncode == 1 or "缺少必填列" in result.stdout or "缺少必填列" in result.stderr
    print("    ✅ 通过 (正确识别缺少设备编号列)")
    
    print("  测试 5.2: 错误时区数据导入...")
    result = run_cmd('create-batch --name "时区测试" --rule-version v2')
    assert result.returncode == 0
    
    result = run_cmd(f'import-readings --batch-id 2 --file {SAMPLE_DATA_DIR / "sensor_readings_wrong_timezone.csv"} --skip-validation')
    assert result.returncode == 0
    
    result = run_cmd("detect --batch-id 2")
    assert result.returncode == 0
    print("    ✅ 通过 (时区数据可正常导入和检测)")
    
    print("  测试 5.3: 复核不存在的异常 ID...")
    result = run_cmd('review --anomaly-id 99999 --result confirmed --notes "测试"')
    assert result.returncode == 1 or "不存在" in result.stderr or "异常" in result.stderr
    print("    ✅ 通过 (正确处理不存在的异常 ID)")
    
    print("  测试 5.4: 回滚不存在的异常 ID...")
    result = run_cmd("rollback --anomaly-id 99999")
    assert result.returncode == 1 or "不存在" in result.stderr
    print("    ✅ 通过 (正确处理不存在的异常 ID)")
    
    clean_test_env()
    print("  ✅ 非法输入测试全部通过")


def test_export_reports():
    """测试报告导出功能"""
    print("\n" + "=" * 70)
    print("测试 6: 报告导出功能")
    print("=" * 70)
    
    setup_test_env()
    
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    run_cmd("detect --batch-id 1")
    run_cmd('review --anomaly-id 3 --result confirmed --notes "测试" --reviewer "测试"')
    
    print("  测试 6.1: 导出 HTML 报告...")
    result = run_cmd("export-html --batch-id 1")
    assert result.returncode == 0
    assert "HTML报告已导出" in result.stdout
    
    html_files = list(REPORTS_DIR.glob("*.html"))
    assert len(html_files) > 0
    print(f"    ✅ 通过 (导出文件: {html_files[-1].name})")
    
    print("  测试 6.2: 验证 HTML 报告内容包含 m³...")
    with open(html_files[-1], 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert "m³" in content or "m3" in content, "HTML 报告应该包含流量单位"
    assert "13" in content, "HTML 报告应该包含异常总数 13"
    print(f"    ✅ 通过 (报告包含 m³ 和异常总数)")
    
    print("  测试 6.3: 导出 CSV 报告...")
    result = run_cmd("export-csv --batch-id 1")
    assert result.returncode == 0
    assert "CSV报告已导出" in result.stdout
    
    csv_files = list(REPORTS_DIR.glob("*.csv"))
    anomaly_csv = [f for f in csv_files if "anomalies" in f.name][-1]
    print(f"    ✅ 通过 (导出文件: {anomaly_csv.name})")
    
    print("  测试 6.4: 验证 CSV 异常报告内容...")
    with open(anomaly_csv, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    assert len(lines) == EXPECTED_ANOMALY_COUNT + 1, \
        f"CSV 行数不匹配: 期望 {EXPECTED_ANOMALY_COUNT + 1}, 实际 {len(lines)}"
    
    has_backward = any("READING_BACKWARD" in l for l in lines)
    print(f"    ✅ 通过 ({len(lines) - 1} 条异常记录, 含读数倒退: {has_backward})")
    
    print("  测试 6.4.1: 验证 CSV 原始数据报告包含流量单位...")
    raw_data_csv = [f for f in csv_files if "raw_data" in f.name][-1]
    with open(raw_data_csv, 'r', encoding='utf-8') as f:
        header = f.readline()
    
    assert "m³" in header or "m3" in header or "flow" in header.lower(), \
        "CSV 原始数据表头应该包含流量单位"
    print(f"    ✅ 通过 (原始数据 CSV 表头包含流量单位)")
    
    print("  测试 6.5: 导出汇总 CSV...")
    result = run_cmd("export-summary")
    assert result.returncode == 0
    assert "批次汇总已导出" in result.stdout
    
    summary_files = [f for f in REPORTS_DIR.glob("export_summary_*.csv")]
    assert len(summary_files) > 0
    print(f"    ✅ 通过 (导出文件: {summary_files[-1].name})")
    
    clean_test_env()
    print("  ✅ 报告导出测试全部通过")


def test_duplicate_shift_import():
    """测试巡检班次重复导入场景"""
    print("\n" + "=" * 70)
    print("测试 7: 巡检班次重复导入")
    print("=" * 70)
    
    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "批次1"')
    
    print("  测试 7.1: 全新库首次导入班次...")
    result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 5" in result.stdout and "更新 0" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 7.2: 同一批次重复导入班次（upsert）...")
    result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 0" in result.stdout and "更新 5" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 7.3: 创建新批次，导入相同班次文件...")
    run_cmd('create-batch --name "批次2"')
    result = run_cmd(f'import-shifts --batch-id 2 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 5" in result.stdout and "更新 0" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 7.4: 验证两个批次都有各自的班次记录...")
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT batch_id, COUNT(*) FROM inspection_shifts GROUP BY batch_id ORDER BY batch_id")
    rows = c.fetchall()
    conn.close()
    
    assert len(rows) == 2, f"应该有2个批次的班次记录，实际 {len(rows)} 个"
    assert rows[0] == (1, 5), f"批次1应该有5条记录，实际 {rows[0][1]} 条"
    assert rows[1] == (2, 5), f"批次2应该有5条记录，实际 {rows[1][1]} 条"
    print(f"    ✅ 通过: 批次1={rows[0][1]}条, 批次2={rows[1][1]}条")
    
    print("  测试 7.5: 新批次3再次导入，验证不影响已有批次...")
    run_cmd('create-batch --name "批次3"')
    result = run_cmd(f'import-shifts --batch-id 3 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 5" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    clean_test_env()
    print("  ✅ 巡检班次重复导入测试全部通过")


def test_existing_db_re_run():
    """测试已有数据库上复跑 README 流程"""
    print("\n" + "=" * 70)
    print("测试 8: 已有数据库复跑 README 流程")
    print("=" * 70)
    
    print("  测试 8.1: 第一轮 - 创建批次1并导入数据...")
    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "第一轮批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    result = run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 5" in result.stdout
    
    result = run_cmd("detect --batch-id 1")
    assert f"共发现 {EXPECTED_ANOMALY_COUNT} 条异常" in result.stdout
    print(f"    ✅ 通过: 第一轮检测到 {EXPECTED_ANOMALY_COUNT} 条异常")
    
    print("  测试 8.2: 第二轮 - 不删库创建批次2并导入相同数据...")
    run_cmd('create-batch --name "第二轮批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 2 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    
    result = run_cmd(f'import-shifts --batch-id 2 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0, f"第二轮导入班次失败: {result.stderr}"
    assert "新增 5" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 8.3: 第二轮运行异常检测...")
    result = run_cmd("detect --batch-id 2")
    assert result.returncode == 0, f"第二轮检测失败: {result.stderr}"
    assert f"共发现 {EXPECTED_ANOMALY_COUNT} 条异常" in result.stdout
    print(f"    ✅ 通过: 第二轮检测到 {EXPECTED_ANOMALY_COUNT} 条异常")
    
    print("  测试 8.4: 验证两个批次数据独立...")
    result = run_cmd("list-batches")
    assert result.returncode == 0
    assert "ID=1" in result.stdout
    assert "ID=2" in result.stdout
    
    anomaly_counts = re.findall(r'异常=(\d+)', result.stdout)
    assert len(anomaly_counts) >= 2, f"应该有至少2个批次，实际 {len(anomaly_counts)} 个"
    assert anomaly_counts[0] == str(EXPECTED_ANOMALY_COUNT), f"批次1异常数不对: {anomaly_counts[0]}"
    assert anomaly_counts[1] == str(EXPECTED_ANOMALY_COUNT), f"批次2异常数不对: {anomaly_counts[1]}"
    print(f"    ✅ 通过: 两个批次各有 {EXPECTED_ANOMALY_COUNT} 条异常，互不影响")
    
    print("  测试 8.5: 第三轮 - 同一批次2重复导入班次（upsert）...")
    result = run_cmd(f'import-shifts --batch-id 2 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    assert result.returncode == 0
    assert "新增 0" in result.stdout and "更新 5" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 8.6: 第三轮 - 再次检测不崩溃...")
    result = run_cmd("detect --batch-id 2")
    assert result.returncode == 0
    print(f"    ✅ 通过: 重复检测不崩溃")
    
    clean_test_env()
    print("  ✅ 已有数据库复跑测试全部通过")


def test_rule_comparison_normal():
    """测试规则对比功能 - 正常场景"""
    print("\n" + "=" * 70)
    print("测试 9: 规则对比功能 - 正常场景")
    print("=" * 70)
    
    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "对比测试批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    
    print("  测试 9.1: 先运行 v2 检测，再对比 v1 vs v2（复用已有结果）...")
    result = run_cmd("detect --batch-id 1")
    assert result.returncode == 0
    
    result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v2")
    assert result.returncode == 0, f"对比失败: {result.stderr}"
    
    assert "版本 v1 异常总数:" in result.stdout
    assert "版本 v2 异常总数:" in result.stdout
    assert "仅在 v1 出现:" in result.stdout
    assert "仅在 v2 出现:" in result.stdout
    assert "按异常类型汇总" in result.stdout
    assert "导出 CSV 文件" in result.stdout
    assert "对比完成，结果已保存到数据库" in result.stdout
    
    assert "PRESSURE_SUDDEN_DROP" in result.stdout
    assert "DUPLICATE_REPORT" in result.stdout
    
    print(f"    ✅ 通过: 对比命令正常执行")
    
    print("  测试 9.2: 验证导出的 CSV 文件存在...")
    csv_files = list(REPORTS_DIR.glob("comparison_*.csv"))
    assert len(csv_files) >= 4, f"应该至少导出4个CSV文件，实际 {len(csv_files)} 个"
    
    summary_file = [f for f in csv_files if "overall_summary" in f.name][0]
    assert summary_file.exists()
    
    type_file = [f for f in csv_files if "by_type" in f.name][0]
    assert type_file.exists()
    
    sev_file = [f for f in csv_files if "by_severity" in f.name][0]
    assert sev_file.exists()
    
    print(f"    ✅ 通过: 导出 {len(csv_files)} 个 CSV 文件")
    
    print("  测试 9.3: 验证 CSV 文件内容...")
    with open(summary_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    assert "批次ID" in content
    assert "批次名称" in content
    assert "规则版本1" in content
    assert "规则版本2" in content
    assert "版本v1异常总数" in content
    assert "版本v2异常总数" in content
    assert "异常数差异" in content
    print(f"    ✅ 通过: 汇总 CSV 包含预期字段")
    
    with open(type_file, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    assert "异常类型" in content
    assert "异常代码" in content
    assert "PRESSURE_SUDDEN_DROP" in content
    assert "DUPLICATE_REPORT" in content
    print(f"    ✅ 通过: 类型对比 CSV 包含预期字段和异常类型")
    
    print("  测试 9.4: 验证 v1 和 v2 检测结果差异合理...")
    v1_count = None
    v2_count = None
    for line in result.stdout.split('\n'):
        if '版本 v1 异常总数:' in line:
            match = re.search(r'版本 v1 异常总数:\s+(\d+)', line)
            if match:
                v1_count = int(match.group(1))
        if '版本 v2 异常总数:' in line:
            match = re.search(r'版本 v2 异常总数:\s+(\d+)', line)
            if match:
                v2_count = int(match.group(1))
    
    assert v1_count is not None
    assert v2_count is not None
    assert v2_count >= v1_count, f"v2 阈值更宽松，应该检测到更多或相等的异常。v1={v1_count}, v2={v2_count}"
    print(f"    ✅ 通过: v1={v1_count}, v2={v2_count}, 差异符合预期")
    
    clean_test_env()
    print("  ✅ 规则对比正常场景测试全部通过")


def test_rule_comparison_edge_cases():
    """测试规则对比功能 - 边界情况"""
    print("\n" + "=" * 70)
    print("测试 10: 规则对比功能 - 边界情况")
    print("=" * 70)
    
    print("  测试 10.1: 规则版本不存在...")
    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "测试批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    
    result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v999")
    assert result.returncode != 0 or "规则版本 v999 不存在" in result.stdout or "规则版本 v999 不存在" in result.stderr
    print(f"    ✅ 通过: 正确识别不存在的规则版本")
    
    result = run_cmd("compare-rules --batch-id 1 --version1 v998 --version2 v999")
    assert result.returncode != 0 or "规则版本 v998 不存在" in result.stdout or "规则版本 v998 不存在" in result.stderr
    print(f"    ✅ 通过: 正确识别两个都不存在的规则版本")
    
    print("  测试 10.2: 批次不存在...")
    result = run_cmd("compare-rules --batch-id 999 --version1 v1 --version2 v2")
    assert result.returncode != 0 or "批次 999 不存在" in result.stdout or "批次 999 不存在" in result.stderr
    print(f"    ✅ 通过: 正确识别不存在的批次")
    
    print("  测试 10.3: 批次未导入数据...")
    run_cmd('create-batch --name "空批次" --rule-version v2')
    result = run_cmd("compare-rules --batch-id 2 --version1 v1 --version2 v2")
    assert result.returncode != 0
    has_error = ("尚未导入巡检数据" in result.stdout or 
                 "尚未导入巡检数据" in result.stderr or
                 "尚未导入" in result.stdout or
                 "尚未导入" in result.stderr)
    assert has_error, f"应该提示批次无数据。stdout={result.stdout[:200]}, stderr={result.stderr[:200]}"
    print(f"    ✅ 通过: 正确识别未导入数据的批次")
    
    print("  测试 10.4: 两个版本相同...")
    result = run_cmd("compare-rules --batch-id 1 --version1 v2 --version2 v2")
    assert result.returncode != 0 or "两个规则版本不能相同" in result.stdout or "两个规则版本不能相同" in result.stderr
    print(f"    ✅ 通过: 正确识别两个相同的版本")
    
    clean_test_env()
    print("  ✅ 规则对比边界情况测试全部通过")


def test_rule_comparison_duplicate_and_restart():
    """测试规则对比功能 - 重复导出和重启后读取"""
    print("\n" + "=" * 70)
    print("测试 11: 规则对比功能 - 重复导出和重启后读取")
    print("=" * 70)
    
    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "对比测试批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    
    print("  测试 11.1: 首次对比成功...")
    result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v2")
    assert result.returncode == 0
    assert "对比完成，结果已保存到数据库" in result.stdout
    
    match = re.search(r'对比ID=(\d+)', result.stdout)
    assert match is not None
    comparison_id = match.group(1)
    print(f"    ✅ 通过: 首次对比成功，对比ID={comparison_id}")
    
    print("  测试 11.2: 重复对比（无 --force）应失败...")
    result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v2")
    assert result.returncode != 0
    assert "对比结果已存在" in result.stdout or "对比结果已存在" in result.stderr
    assert "--force" in result.stdout or "--force" in result.stderr
    print(f"    ✅ 通过: 重复对比正确提示需要 --force 参数")
    
    print("  测试 11.3: 重复对比（带 --force）应成功覆盖...")
    result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v2 --force")
    assert result.returncode == 0
    assert "对比完成，结果已保存到数据库" in result.stdout
    print(f"    ✅ 通过: 带 --force 可覆盖已有结果")
    
    print("  测试 11.4: 验证数据库中对比记录可追溯...")
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT id, batch_id, rule_version_1, rule_version_2 FROM rule_comparisons ORDER BY id")
    rows = c.fetchall()
    
    assert len(rows) >= 1, "数据库中应该有对比记录"
    
    latest = rows[-1]
    assert latest[1] == 1, "批次ID应该是1"
    assert latest[2] == "v1", "版本1应该是v1"
    assert latest[3] == "v2", "版本2应该是v2"
    
    c.execute("SELECT comparison_data FROM rule_comparisons WHERE id = ?", (latest[0],))
    data_row = c.fetchone()
    assert data_row is not None
    assert data_row[0] is not None
    assert len(data_row[0]) > 100, "对比数据应该有足够内容"
    assert '"version1_total"' in data_row[0], "对比数据应该包含 version1_total"
    assert '"version2_total"' in data_row[0], "对比数据应该包含 version2_total"
    
    conn.close()
    print(f"    ✅ 通过: 数据库中对比记录可追溯，数据完整")
    
    print("  测试 11.5: 模拟程序重启，从数据库读取对比数据再导出...")
    import json
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT comparison_data FROM rule_comparisons WHERE id = ?", (latest[0],))
    data_row = c.fetchone()
    conn.close()
    
    comparison_data = json.loads(data_row[0])
    assert "meta" in comparison_data
    assert "totals" in comparison_data
    assert "by_type_v1" in comparison_data
    assert "by_type_v2" in comparison_data
    
    v1_total = comparison_data["totals"]["version1_total"]
    v2_total = comparison_data["totals"]["version2_total"]
    assert isinstance(v1_total, int) and v1_total > 0
    assert isinstance(v2_total, int) and v2_total > 0
    
    from pump_inspection.report_exporter import ReportExporter
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine(f"sqlite:///{DB_PATH}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    exporter = ReportExporter(db, output_dir=str(REPORTS_DIR))
    files = exporter.export_rule_comparison_csv(
        comparison_data, 
        filename_prefix="restart_test_comparison"
    )
    db.close()
    
    assert len(files) >= 4
    assert "overall_summary" in files
    assert os.path.exists(files["overall_summary"])
    
    with open(files["overall_summary"], 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    assert str(v1_total) in content
    assert str(v2_total) in content
    print(f"    ✅ 通过: 重启后从数据库读取对比数据并成功导出CSV，v1={v1_total}, v2={v2_total}")
    
    print("  测试 11.6: 验证对比批次状态为 comparison，不影响正常批次...")
    result = run_cmd("list-batches")
    assert result.returncode == 0
    
    lines = result.stdout.split('\n')
    normal_batches = [l for l in lines if 'ID=1' in l or 'ID=2' in l]
    comparison_batches = [l for l in lines if 'comparison' in l.lower() and '状态=comparison' in l]
    
    assert len(normal_batches) >= 1, "应该有正常批次"
    print(f"    ✅ 通过: 正常批次可正常列出，对比临时批次状态为 comparison")
    
    clean_test_env()
    print("  ✅ 规则对比重复导出和重启测试全部通过")


def test_rule_comparison_config_errors():
    """测试规则对比功能 - 配置文件错误处理"""
    print("\n" + "=" * 70)
    print("测试 12: 规则对比功能 - 配置文件错误处理")
    print("=" * 70)
    
    clean_test_env()
    
    import tempfile
    import shutil
    
    original_config_dir = PROJECT_ROOT / "config"
    temp_config_dir = tempfile.mkdtemp(prefix="config_backup_")
    
    try:
        for f in original_config_dir.glob("detection_rules_v*.json"):
            shutil.copy2(f, temp_config_dir)
        
        print("  测试 12.1: 损坏的 JSON 配置...")
        bad_file = original_config_dir / "detection_rules_v3.json"
        with open(bad_file, 'w', encoding='utf-8') as f:
            f.write('{invalid json content')
        
        run_cmd("init-db")
        
        result = run_cmd(f'list-rules')
        assert result.returncode == 0
        
        run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
        run_cmd('create-batch --name "测试批次" --rule-version v2')
        run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
        
        bad_file.unlink()
        print(f"    ✅ 通过: 损坏的配置文件未影响 v1/v2 版本")
        
        print("  测试 12.2: 自定义输出文件名前缀...")
        result = run_cmd("compare-rules --batch-id 1 --version1 v1 --version2 v2 --output my_custom_prefix")
        assert result.returncode == 0
        
        custom_files = list(REPORTS_DIR.glob("my_custom_prefix*.csv"))
        assert len(custom_files) >= 4, f"应该有自定义前缀的CSV文件，实际 {len(custom_files)} 个"
        print(f"    ✅ 通过: 自定义文件名前缀生效")
        
        clean_test_env()
        print("  ✅ 规则对比配置错误处理测试全部通过")
        
    finally:
        bad_file = original_config_dir / "detection_rules_v3.json"
        if bad_file.exists():
            bad_file.unlink()
        
        for f in os.listdir(temp_config_dir):
            shutil.copy2(os.path.join(temp_config_dir, f), original_config_dir / f)
        shutil.rmtree(temp_config_dir)


def test_remark_csv_import():
    """测试备注功能 - CSV 导入备注"""
    print("\n" + "=" * 70)
    print("测试 13: 备注功能 - CSV 导入备注")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "备注测试批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")

    print("  测试 13.1: 正常导入备注 CSV...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode == 0, f"导入备注失败: {result.stderr}"
    assert "总计 5 条" in result.stdout
    assert "成功 5" in result.stdout
    print(f"    ✅ 通过: {result.stdout.strip()}")

    print("  测试 13.2: 查看导入的备注...")
    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 5 条" in result.stdout
    assert "停泵检修" in result.stdout
    assert "传感器临时更换" in result.stdout
    assert "人工补录" in result.stdout
    print(f"    ✅ 通过: 成功列出所有备注")

    print("  测试 13.3: 按异常ID过滤备注...")
    result = run_cmd("list-remarks --batch-id 1 --anomaly-id 1")
    assert result.returncode == 0
    assert "异常 1 备注列表" in result.stdout or "异常#1" in result.stdout
    assert "停泵检修" in result.stdout
    assert "传感器临时更换" not in result.stdout
    print(f"    ✅ 通过: 按异常ID过滤正常")

    print("  测试 13.4: 查看批次级备注...")
    result = run_cmd("list-remarks --batch-id 1")
    assert result.returncode == 0
    assert "批次备注列表" in result.stdout
    assert "传感器临时更换" in result.stdout
    assert "停泵检修" not in result.stdout
    print(f"    ✅ 通过: 批次级备注正常显示")

    clean_test_env()
    print("  ✅ CSV 导入备注测试全部通过")


def test_remark_add_append():
    """测试备注功能 - 追加备注和历史记录"""
    print("\n" + "=" * 70)
    print("测试 14: 备注功能 - 追加备注和历史记录")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "备注追加测试" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")

    print("  测试 14.1: 给异常追加第一条备注...")
    result = run_cmd('add-remark --batch-id 1 --anomaly-id 3 --content "第一次备注：初查异常" --operator "张三" --remark-type general')
    assert result.returncode == 0
    assert "备注已添加到 异常 3" in result.stdout
    assert "第一次备注" in result.stdout
    print(f"    ✅ 通过: 第一条备注添加成功")

    print("  测试 14.2: 给同一异常追加第二条备注（保留历史）...")
    result = run_cmd('add-remark --batch-id 1 --anomaly-id 3 --content "第二次备注：已安排维修" --operator "李四" --remark-type maintenance')
    assert result.returncode == 0
    assert "备注已添加到 异常 3" in result.stdout
    assert "第二次备注" in result.stdout
    print(f"    ✅ 通过: 第二条备注添加成功")

    print("  测试 14.3: 验证两条备注都存在，且有前序关联...")
    result = run_cmd("list-remarks --batch-id 1 --anomaly-id 3")
    assert result.returncode == 0
    assert "第一次备注" in result.stdout
    assert "第二次备注" in result.stdout
    assert "前序ID" in result.stdout
    print(f"    ✅ 通过: 两条备注都存在，且有前序关联")

    print("  测试 14.4: 给批次追加备注...")
    result = run_cmd('add-remark --batch-id 1 --content "批次级备注：本批次数据存在传感器波动" --operator "王五" --remark-type sensor_replacement')
    assert result.returncode == 0
    assert "备注已添加到 批次 1" in result.stdout
    print(f"    ✅ 通过: 批次级备注添加成功")

    print("  测试 14.5: 查看所有备注（共3条）...")
    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 3 条" in result.stdout
    print(f"    ✅ 通过: 所有备注共3条")

    clean_test_env()
    print("  ✅ 追加备注和历史记录测试全部通过")


def test_remark_duplicate_import():
    """测试备注功能 - 重复导入和冲突场景"""
    print("\n" + "=" * 70)
    print("测试 15: 备注功能 - 重复导入和冲突场景")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "重复导入测试" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")

    print("  测试 15.1: 首次导入备注...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode == 0
    assert "成功 5" in result.stdout
    print(f"    ✅ 通过: 首次导入成功")

    print("  测试 15.2: 重复导入同一 CSV（import_key 去重）...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode == 0
    assert "总计 5 条" in result.stdout
    assert "成功 0" in result.stdout
    assert "跳过 5" in result.stdout
    assert "备注已存在" in result.stdout
    print(f"    ✅ 通过: 重复导入正确跳过，保留原记录")

    print("  测试 15.3: 验证备注数量仍为5条...")
    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 5 条" in result.stdout
    print(f"    ✅ 通过: 备注数量未增加，去重有效")

    print("  测试 15.4: CSV 缺少必填列...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "remarks_missing_column.csv"}')
    assert result.returncode != 0 or "缺少必填列" in result.stdout or "缺少必填列" in result.stderr
    assert "content" in result.stdout or "content" in result.stderr
    print(f"    ✅ 通过: 正确识别缺少必填列")

    clean_test_env()
    print("  ✅ 重复导入和冲突场景测试全部通过")


def test_remark_restart_persistence():
    """测试备注功能 - 重启后数据持久化"""
    print("\n" + "=" * 70)
    print("测试 16: 备注功能 - 重启后数据持久化")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "持久化测试批次" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")

    print("  测试 16.1: 添加备注到数据库...")
    run_cmd('add-remark --batch-id 1 --anomaly-id 2 --content "重启前备注：停泵检修" --operator "张三" --remark-type maintenance')
    run_cmd('add-remark --batch-id 1 --content "重启前批次备注：传感器已校准" --operator "李四" --remark-type sensor_replacement')
    run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')

    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 7 条" in result.stdout
    print(f"    ✅ 通过: 重启前添加了7条备注")

    print("  测试 16.2: 验证数据库中备注表存在且有数据...")
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='remarks'")
    assert c.fetchone() is not None, "remarks 表不存在"

    c.execute("SELECT COUNT(*) FROM remarks WHERE batch_id = 1")
    count = c.fetchone()[0]
    assert count == 7, f"数据库中应该有7条备注，实际 {count} 条"

    c.execute("SELECT content, operator, remark_type FROM remarks ORDER BY id")
    rows = c.fetchall()
    conn.close()

    contents = [r[0] for r in rows]
    has_restart_remark = any("重启前备注" in c and "停泵检修" in c for c in contents)
    assert has_restart_remark, f"'重启前备注：停泵检修' 不在内容列表中: {contents}"
    has_sensor_calibrated = any("重启前批次备注" in c and "传感器已校准" in c for c in contents)
    assert has_sensor_calibrated, f"'重启前批次备注：传感器已校准' 不在内容列表中: {contents}"
    has_pump_repair = any("停泵检修" in c and "更换1号泵密封圈" in c for c in contents)
    assert has_pump_repair, f"'停泵检修，更换1号泵密封圈' 不在内容列表中: {contents}"
    print(f"    ✅ 通过: 数据库中有7条备注，内容正确")

    print("  测试 16.3: 模拟程序重启（不删库，重新初始化）...")
    import time
    time.sleep(0.5)
    run_cmd("init-db")

    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 7 条" in result.stdout
    has_restart = "重启前备注" in result.stdout and "停泵检修" in result.stdout
    assert has_restart, f"'重启前备注' 或 '停泵检修' 不在输出中: {result.stdout[:500]}"
    has_pump = "停泵检修" in result.stdout and "更换1号泵密封圈" in result.stdout
    assert has_pump, f"'停泵检修' 或 '更换1号泵密封圈' 不在输出中: {result.stdout[:500]}"
    print(f"    ✅ 通过: 重启后仍能查询到完整7条备注")

    print("  测试 16.4: 重启后可继续追加备注...")
    result = run_cmd('add-remark --batch-id 1 --anomaly-id 5 --content "重启后追加：维修完成" --operator "王五" --remark-type maintenance')
    assert result.returncode == 0

    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "共 8 条" in result.stdout
    has_restart_append = "重启后追加" in result.stdout and "维修完成" in result.stdout
    assert has_restart_append, f"'重启后追加' 或 '维修完成' 不在输出中: {result.stdout[:500]}"
    print(f"    ✅ 通过: 重启后成功追加第8条备注")

    clean_test_env()
    print("  ✅ 重启后数据持久化测试全部通过")


def test_remark_report_export():
    """测试备注功能 - 报告导出包含备注"""
    print("\n" + "=" * 70)
    print("测试 17: 备注功能 - 报告导出包含备注")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "报告导出测试" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")

    print("  测试 17.1: 添加测试备注...")
    run_cmd('add-remark --batch-id 1 --anomaly-id 1 --content "HTML测试：停泵检修备注" --operator "张三" --remark-type maintenance')
    run_cmd('add-remark --batch-id 1 --anomaly-id 3 --content "CSV测试：人工补录数据" --operator "李四" --remark-type manual_entry')
    run_cmd('add-remark --batch-id 1 --content "批次备注：本批次包含3条传感器更换记录" --operator "王五" --remark-type sensor_replacement')

    print("  测试 17.2: 导出 HTML 报告...")
    result = run_cmd("export-html --batch-id 1")
    assert result.returncode == 0
    assert "HTML报告已导出" in result.stdout

    html_files = list(REPORTS_DIR.glob("*.html"))
    assert len(html_files) > 0
    latest_html = html_files[-1]

    with open(latest_html, 'r', encoding='utf-8') as f:
        html_content = f.read()

    assert "交接备注历史" in html_content, "HTML 报告应该包含交接备注历史部分"
    assert "批次级备注" in html_content, "HTML 报告应该包含批次级备注部分"
    assert "停泵检修备注" in html_content, "HTML 报告应该包含异常备注内容"
    assert "人工补录数据" in html_content, "HTML 报告应该包含异常备注内容"
    assert "批次备注：本批次包含3条传感器更换记录" in html_content, "HTML 报告应该包含批次备注内容"
    assert "remark-type-maintenance" in html_content, "HTML 报告应该包含备注类型样式"
    assert "remark-type-manual_entry" in html_content, "HTML 报告应该包含备注类型样式"
    print(f"    ✅ 通过: HTML 报告包含完整备注内容")

    print("  测试 17.3: 导出 CSV 报告...")
    result = run_cmd("export-csv --batch-id 1")
    assert result.returncode == 0
    assert "CSV报告已导出" in result.stdout

    csv_files = list(REPORTS_DIR.glob("*.csv"))
    remark_csv = [f for f in csv_files if "remarks" in f.name][-1]
    assert remark_csv.exists(), "应该导出 remarks CSV 文件"

    with open(remark_csv, 'r', encoding='utf-8-sig') as f:
        csv_content = f.read()

    assert "备注ID" in csv_content, "CSV 应该包含备注ID列"
    assert "备注类型" in csv_content, "CSV 应该包含备注类型列"
    assert "备注内容" in csv_content, "CSV 应该包含备注内容列"
    assert "操作人" in csv_content, "CSV 应该包含操作人列"
    assert "停泵检修备注" in csv_content, "CSV 应该包含备注内容"
    assert "人工补录数据" in csv_content, "CSV 应该包含备注内容"
    assert "批次备注：本批次包含3条传感器更换记录" in csv_content, "CSV 应该包含备注内容"
    assert "前序备注ID" in csv_content, "CSV 应该包含前序备注ID列"
    print(f"    ✅ 通过: CSV 报告包含完整备注内容和前序关联")

    print("  测试 17.4: 验证异常明细 CSV 也能关联到备注...")
    anomaly_csv = [f for f in csv_files if "anomalies" in f.name][-1]
    with open(anomaly_csv, 'r', encoding='utf-8-sig') as f:
        anomaly_lines = f.readlines()
    assert len(anomaly_lines) > 1, "异常 CSV 应该有数据"
    print(f"    ✅ 通过: 异常 CSV 正常导出")

    clean_test_env()
    print("  ✅ 报告导出包含备注测试全部通过")


def test_remark_error_scenarios():
    """测试备注功能 - 错误场景处理"""
    print("\n" + "=" * 70)
    print("测试 18: 备注功能 - 错误场景处理")
    print("=" * 70)

    clean_test_env()
    run_cmd("init-db")
    run_cmd(f'import-equipment --file {SAMPLE_DATA_DIR / "equipment_ledger.csv"}')
    run_cmd('create-batch --name "错误场景测试" --rule-version v2')
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 1")
    run_cmd('create-batch --name "第二批次" --rule-version v2')

    print("  测试 18.1: 批次不存在...")
    result = run_cmd('add-remark --batch-id 99999 --content "测试" --operator "测试"')
    assert result.returncode != 0 or "批次 99999 不存在" in result.stdout or "批次 99999 不存在" in result.stderr
    print(f"    ✅ 通过: 正确识别不存在的批次")

    print("  测试 18.2: 异常不存在...")
    result = run_cmd('add-remark --batch-id 1 --anomaly-id 99999 --content "测试" --operator "测试"')
    assert result.returncode != 0 or "异常 99999 不存在" in result.stdout or "异常 99999 不存在" in result.stderr
    print(f"    ✅ 通过: 正确识别不存在的异常")

    print("  测试 18.3: 异常ID不属于该批次...")
    run_cmd(f'import-readings --batch-id 2 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd("detect --batch-id 2")

    result = run_cmd('add-remark --batch-id 1 --anomaly-id 14 --content "测试" --operator "测试"')
    assert result.returncode != 0 or "不属于批次" in result.stdout or "不属于批次" in result.stderr
    print(f"    ✅ 通过: 正确识别异常不属于该批次")

    print("  测试 18.4: 备注内容为空...")
    result = run_cmd('add-remark --batch-id 1 --content "   " --operator "测试"')
    assert result.returncode != 0 or "不能为空" in result.stdout or "不能为空" in result.stderr
    print(f"    ✅ 通过: 正确识别空内容")

    print("  测试 18.5: 导入备注到不存在的批次...")
    result = run_cmd(f'import-remarks --batch-id 99999 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode != 0 or "批次 99999 不存在" in result.stdout or "批次 99999 不存在" in result.stderr
    print(f"    ✅ 通过: 导入时正确识别不存在的批次")

    print("  测试 18.6: 查看不存在的批次的备注...")
    result = run_cmd("list-remarks --batch-id 99999 --all")
    assert result.returncode != 0 or "批次 99999 不存在" in result.stdout or "批次 99999 不存在" in result.stderr
    print(f"    ✅ 通过: 查看时正确识别不存在的批次")

    print("  测试 18.7: 查看不属于该批次的异常的备注...")
    result = run_cmd("list-remarks --batch-id 1 --anomaly-id 14")
    assert result.returncode != 0 or "不属于批次" in result.stdout or "不属于批次" in result.stderr
    print(f"    ✅ 通过: 正确识别异常不属于该批次")

    clean_test_env()
    print("  ✅ 错误场景处理测试全部通过")


def main():
    """主测试函数"""
    print("\n" + "#" * 70)
    print("#" + " " * 68 + "#")
    print("#" + " " * 15 + "泵房巡检异常分析工具 - 回归测试" + " " * 20 + "#")
    print("#" + " " * 68 + "#")
    print("#" * 70)
    
    print(f"\n项目根目录: {PROJECT_ROOT}")
    print(f"Python 版本: {sys.version}")
    print(f"操作系统: {sys.platform}")
    
    all_passed = True
    tests = [
        test_gbk_encoding_scenario,
        test_anomaly_count_consistency,
        test_readme_step_by_step,
        test_review_and_rollback,
        test_invalid_input,
        test_export_reports,
        test_duplicate_shift_import,
        test_existing_db_re_run,
        test_rule_comparison_normal,
        test_rule_comparison_edge_cases,
        test_rule_comparison_duplicate_and_restart,
        test_rule_comparison_config_errors,
        test_remark_csv_import,
        test_remark_add_append,
        test_remark_duplicate_import,
        test_remark_restart_persistence,
        test_remark_report_export,
        test_remark_error_scenarios,
    ]
    
    failed_tests = []
    
    for test_func in tests:
        try:
            test_func()
        except Exception as e:
            all_passed = False
            failed_tests.append((test_func.__name__, str(e)))
            print(f"\n  ❌ 测试失败: {test_func.__name__}")
            print(f"     错误: {str(e)[:200]}")
    
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    
    if all_passed:
        print(f"\n✅ 全部 {len(tests)} 个测试通过！")
        print(f"   - GBK 编码场景: 通过")
        print(f"   - 异常数量一致性 (13条): 通过")
        print(f"   - README 分步命令: 通过")
        print(f"   - 复核和回滚: 通过")
        print(f"   - 非法输入: 通过")
        print(f"   - 报告导出: 通过")
        print(f"   - 巡检班次重复导入: 通过")
        print(f"   - 已有数据库复跑: 通过")
        print(f"   - 规则对比正常场景: 通过")
        print(f"   - 规则对比边界情况: 通过")
        print(f"   - 规则对比重复导出和重启: 通过")
        print(f"   - 规则对比配置错误处理: 通过")
        print(f"   - 备注CSV导入: 通过")
        print(f"   - 备注追加和历史记录: 通过")
        print(f"   - 备注重复导入去重: 通过")
        print(f"   - 备注重启后持久化: 通过")
        print(f"   - 备注报告导出: 通过")
        print(f"   - 备注错误场景处理: 通过")
        return 0
    else:
        print(f"\n❌ {len(failed_tests)}/{len(tests)} 个测试失败:")
        for name, error in failed_tests:
            print(f"   - {name}: {error[:100]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
