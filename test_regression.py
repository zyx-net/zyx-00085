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


def test_remark_functions():
    """测试备注功能 - 导入、追加、查看、重复导入、报告导出"""
    print("\n" + "=" * 70)
    print("测试 9: 备注功能完整验证")
    print("=" * 70)
    
    setup_test_env()
    
    run_cmd(f'import-readings --batch-id 1 --file {SAMPLE_DATA_DIR / "sensor_readings_with_anomalies.csv"}')
    run_cmd(f'import-shifts --batch-id 1 --file {SAMPLE_DATA_DIR / "inspection_shifts.csv"}')
    run_cmd("detect --batch-id 1")
    
    print("  测试 9.1: 从 CSV 导入备注...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode == 0, f"导入备注失败: {result.stderr}"
    assert "备注导入完成" in result.stdout, f"输出应该包含导入完成提示: {result.stdout}"
    print(f"    ✅ 通过: {result.stdout.strip()}")
    
    print("  测试 9.2: 查看批次级备注...")
    result = run_cmd("list-remarks --batch-id 1")
    assert result.returncode == 0
    assert "批次级备注列表" in result.stdout
    batch_remark_count = len([l for l in result.stdout.split('\n') if l.strip().startswith('ID=') and '异常ID' not in l])
    print(f"    ✅ 通过: 找到 {batch_remark_count} 条批次级备注")
    
    print("  测试 9.3: 查看异常级备注（异常ID=1）...")
    result = run_cmd("list-remarks --batch-id 1 --anomaly-id 1")
    assert result.returncode == 0
    assert "异常级备注列表" in result.stdout
    anomaly_remark_count = len([l for l in result.stdout.split('\n') if l.strip().startswith('ID=')])
    assert anomaly_remark_count >= 1, "应该至少有1条异常级备注"
    print(f"    ✅ 通过: 找到 {anomaly_remark_count} 条异常级备注")
    
    print("  测试 9.4: 查看全部备注...")
    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    assert "全部备注列表" in result.stdout
    all_remark_count = len([l for l in result.stdout.split('\n') if l.strip().startswith('ID=')])
    assert all_remark_count >= 5, f"应该至少有5条备注（sample_remarks.csv有6条），实际 {all_remark_count}"
    print(f"    ✅ 通过: 找到 {all_remark_count} 条全部备注")
    
    print("  测试 9.5: 重复导入备注（去重验证）...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "sample_remarks.csv"}')
    assert result.returncode == 0
    assert "跳过" in result.stdout or "备注已存在" in result.stdout
    stats_line = [l for l in result.stdout.split('\n') if '备注导入完成' in l][0]
    assert "导入 0" in stats_line or "跳过" in stats_line, f"重复导入应该跳过所有: {stats_line}"
    print(f"    ✅ 通过: {stats_line.strip()}")
    
    print("  测试 9.6: 单条追加批次级备注...")
    result = run_cmd('add-remark --batch-id 1 --content "测试批次级备注内容" --operator "测试员" --remark-type general')
    assert result.returncode == 0
    assert "备注添加成功" in result.stdout
    assert "类型=general" in result.stdout
    assert "操作人=测试员" in result.stdout
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    print(f"    ✅ 通过: {first_line}")
    
    print("  测试 9.7: 单条追加异常级备注...")
    result = run_cmd('add-remark --batch-id 1 --anomaly-id 2 --content "测试异常级备注内容" --operator "测试员2" --remark-type maintenance')
    assert result.returncode == 0
    assert "备注添加成功" in result.stdout
    assert "类型=maintenance" in result.stdout
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    print(f"    ✅ 通过: {first_line}")
    
    print("  测试 9.8: 验证追加后备注总数...")
    result = run_cmd("list-remarks --batch-id 1 --all")
    assert result.returncode == 0
    new_count = len([l for l in result.stdout.split('\n') if l.strip().startswith('ID=')])
    assert new_count == all_remark_count + 2, f"应该增加2条备注，期望 {all_remark_count + 2}，实际 {new_count}"
    print(f"    ✅ 通过: 总数 {new_count} 条（增加2条）")
    
    print("  测试 9.9: 测试缺少必填列的 CSV...")
    result = run_cmd(f'import-remarks --batch-id 1 --file {SAMPLE_DATA_DIR / "remarks_missing_column.csv"}')
    assert result.returncode == 1 or "缺少必填列" in result.stdout or "缺少必填列" in result.stderr
    print(f"    ✅ 通过: 正确识别缺少必填列")
    
    print("  测试 9.10: 导出 HTML 报告（包含备注）...")
    result = run_cmd("export-html --batch-id 1")
    assert result.returncode == 0
    assert "HTML报告已导出" in result.stdout
    
    html_files = list(REPORTS_DIR.glob("*.html"))
    assert len(html_files) > 0
    with open(html_files[-1], 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    assert "备注信息" in html_content, "HTML 报告应该包含备注信息部分"
    assert "批次级备注" in html_content or "异常级备注" in html_content
    assert "测试批次级备注内容" in html_content, "HTML 应该包含新增的批次级备注"
    assert "测试异常级备注内容" in html_content, "HTML 应该包含新增的异常级备注"
    print(f"    ✅ 通过: HTML 报告包含备注信息")
    
    print("  测试 9.11: 导出 CSV 报告（包含备注）...")
    result = run_cmd("export-csv --batch-id 1")
    assert result.returncode == 0
    assert "CSV报告已导出" in result.stdout
    
    csv_files = list(REPORTS_DIR.glob("*.csv"))
    remark_csv = [f for f in csv_files if "remarks" in f.name]
    assert len(remark_csv) > 0, "应该有 remarks CSV 文件"
    
    with open(remark_csv[-1], 'r', encoding='utf-8') as f:
        remark_lines = f.readlines()
    
    assert len(remark_lines) >= 3, f"备注 CSV 应该有表头+至少2条数据，实际 {len(remark_lines)} 行"
    assert "测试批次级备注内容" in ''.join(remark_lines), "CSV 应该包含新增的批次级备注"
    assert "测试异常级备注内容" in ''.join(remark_lines), "CSV 应该包含新增的异常级备注"
    print(f"    ✅ 通过: CSV 报告包含 {len(remark_lines) - 1} 条备注记录")
    
    print("  测试 9.12: 验证数据库重启后备注仍存在...")
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM remarks WHERE batch_id = 1")
    db_count = c.fetchone()[0]
    conn.close()
    
    assert db_count == new_count, f"数据库中备注数量不匹配: 期望 {new_count}, 实际 {db_count}"
    print(f"    ✅ 通过: 数据库中持久化 {db_count} 条备注")
    
    clean_test_env()
    print("  ✅ 备注功能测试全部通过")


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
        test_remark_functions,
        test_existing_db_re_run,
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
        print(f"   - 备注功能（导入/追加/查看/去重/报告）: 通过")
        print(f"   - 已有数据库复跑: 通过")
        return 0
    else:
        print(f"\n❌ {len(failed_tests)}/{len(tests)} 个测试失败:")
        for name, error in failed_tests:
            print(f"   - {name}: {error[:100]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
