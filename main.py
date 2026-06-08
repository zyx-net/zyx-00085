#!/usr/bin/env python3
import argparse
import sys
import os
import io
from datetime import datetime

from pump_inspection import (
    init_db,
    SessionLocal,
    BatchManager,
    RuleManager,
    ReportExporter,
)


class UnicodeSafeStreamWrapper(io.TextIOWrapper):
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
        sys.stdout = UnicodeSafeStreamWrapper(stdout_bin, encoding='utf-8')
        sys.stderr = UnicodeSafeStreamWrapper(stderr_bin, encoding='utf-8')
    except Exception:
        os.environ.setdefault('PYTHONIOENCODING', 'utf-8:replace')


_setup_unicode_safe_output()

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")


def print_separator(title=""):
    line = "=" * 80
    if title:
        print(f"\n{line}")
        print(f"  {title}")
        print(f"{line}\n")
    else:
        print(f"\n{line}\n")


def cmd_init_db(args):
    """初始化数据库"""
    init_db()
    print("数据库初始化完成")


def cmd_import_equipment(args):
    """导入设备台账"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        file_path = args.file or os.path.join(SAMPLE_DATA_DIR, "equipment_ledger.csv")
        print(f"导入设备台账: {file_path}")
        success, count, errors = batch_manager.import_equipment_ledger(file_path, args.skip_validation)

        if not success:
            print(f"导入失败，错误信息:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        print(f"成功导入/更新 {count} 条设备台账记录")
    finally:
        db.close()


def cmd_list_equipment(args):
    """列出设备台账"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        equipment = batch_manager.get_equipment_ledger()
        print(f"设备台账列表 (共 {len(equipment)} 条):")
        for e in equipment:
            print(f"  {e.device_id} - {e.device_name} ({e.location}) 范围: {e.pressure_low_limit}-{e.pressure_high_limit}MPa")
    finally:
        db.close()


def cmd_create_batch(args):
    """创建批次"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        rule_manager = RuleManager(db)

        rule_version = args.rule_version or rule_manager.get_active_version().version

        batch = batch_manager.create_batch(
            batch_name=args.name,
            rule_version=rule_version,
            source_file=args.source or "",
            notes=args.notes or ""
        )
        print(f"批次创建成功: ID={batch.id}, 名称={batch.batch_name}, 规则版本={batch.rule_version}")
    finally:
        db.close()


def cmd_import_readings(args):
    """导入传感器读数"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        file_path = args.file or os.path.join(SAMPLE_DATA_DIR, "sensor_readings_with_anomalies.csv")
        print(f"导入传感器读数: {file_path}")
        success, unmapped, errors = batch_manager.import_sensor_readings(
            args.batch_id,
            file_path,
            args.skip_validation
        )

        if not success:
            print(f"导入失败，错误信息:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        if unmapped:
            print(f"未映射列: {unmapped}")

        batch = batch_manager.get_batch(args.batch_id)
        print(f"成功导入 {batch.total_records} 条记录")

        if errors:
            print(f"时区/时间问题:")
            for issue in errors:
                print(f"  - 行{issue.get('row')}: {issue.get('message')}")
    finally:
        db.close()


def cmd_import_shifts(args):
    """导入巡检班次"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        file_path = args.file or os.path.join(SAMPLE_DATA_DIR, "inspection_shifts.csv")
        print(f"导入巡检班次: {file_path}")
        success, stats, errors = batch_manager.import_inspection_shifts(args.batch_id, file_path)

        if not success:
            print(f"导入失败，错误信息:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        total = stats.get("total", 0)
        inserted = stats.get("inserted", 0)
        updated = stats.get("updated", 0)
        skipped = stats.get("skipped", 0)
        print(f"巡检班次导入完成: 总计 {total} 条 (新增 {inserted}, 更新 {updated}, 跳过 {skipped})")
    finally:
        db.close()


def cmd_detect(args):
    """运行异常检测"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        rule_manager = RuleManager(db)

        batch = batch_manager.get_batch(args.batch_id)
        if not batch:
            print(f"批次 {args.batch_id} 不存在")
            sys.exit(1)

        rule_config = rule_manager.get_rule_config(batch.rule_version)
        if not rule_config:
            print(f"规则版本 {batch.rule_version} 不存在")
            sys.exit(1)

        print(f"使用规则版本 {batch.rule_version} 进行异常检测...")
        count, anomalies = batch_manager.run_detection(args.batch_id, rule_config)

        print(f"检测完成，共发现 {count} 条异常:")
        summary = batch_manager.get_anomaly_summary(args.batch_id)
        for code, data in summary.items():
            print(f"  {data['name']} ({code}): {data['count']} 条")
    finally:
        db.close()


def cmd_list_batches(args):
    """列出所有批次"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        batches = batch_manager.get_all_batches()
        print(f"批次列表 (共 {len(batches)} 个):")
        for b in batches:
            print(f"  ID={b.id} | 名称={b.batch_name} | 规则={b.rule_version} | "
                  f"状态={b.status} | 记录={b.total_records} | "
                  f"异常={b.anomaly_count} | 已复核={b.reviewed_count} | "
                  f"导入时间={b.import_time}")
    finally:
        db.close()


def cmd_list_anomalies(args):
    """列出批次异常"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)

        reviewed = None
        if args.reviewed == "yes":
            reviewed = True
        elif args.reviewed == "no":
            reviewed = False

        anomalies = batch_manager.get_batch_anomalies(args.batch_id, reviewed)
        print(f"批次 {args.batch_id} 异常列表 (共 {len(anomalies)} 条):")
        for a in anomalies:
            status = "待复核"
            if a.is_reviewed:
                status = f"已复核: {a.review_result}"
            print(f"  ID={a.id} | {a.anomaly_type} ({a.anomaly_code}) | "
                  f"严重度={a.severity} | 设备={a.device_id} | "
                  f"时间={a.reading_time} | {status}")
            print(f"      描述: {a.description}")
    finally:
        db.close()


def cmd_review(args):
    """复核异常"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        record = batch_manager.review_anomaly(
            args.anomaly_id,
            args.result,
            args.notes or "",
            args.reviewer or "admin"
        )
        if record:
            print(f"复核成功: 异常ID={args.anomaly_id}, 结果={args.result}")
        else:
            print(f"复核失败: 异常 {args.anomaly_id} 不存在")
            sys.exit(1)
    finally:
        db.close()


def cmd_rollback(args):
    """回滚复核"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        record = batch_manager.rollback_review(args.anomaly_id)
        if record:
            print(f"回滚成功: 异常ID={args.anomaly_id}")
        else:
            print(f"回滚失败: 异常 {args.anomaly_id} 不存在或未复核")
            sys.exit(1)
    finally:
        db.close()


def cmd_list_rules(args):
    """列出所有规则版本"""
    db = SessionLocal()
    try:
        rule_manager = RuleManager(db)
        versions = rule_manager.get_all_versions()
        print(f"规则版本列表 (共 {len(versions)} 个):")
        for v in versions:
            active = "*" if v.is_active else " "
            print(f"  {active} {v.version} | {v.description} | 创建时间={v.created_at}"
                  f"{' | 基于: ' + v.based_on if v.based_on else ''}")
    finally:
        db.close()


def cmd_use_rule(args):
    """设置使用的规则版本"""
    db = SessionLocal()
    try:
        rule_manager = RuleManager(db)
        success = rule_manager.set_active_version(args.version)
        if success:
            print(f"已设置当前规则版本为 {args.version}")
        else:
            print(f"版本 {args.version} 不存在")
            sys.exit(1)
    finally:
        db.close()


def cmd_export_html(args):
    """导出HTML报告"""
    db = SessionLocal()
    try:
        exporter = ReportExporter(db)
        filepath = exporter.export_html(
            args.batch_id,
            include_raw_data=not args.no_raw_data,
            filename=args.output
        )
        print(f"HTML报告已导出: {filepath}")
    finally:
        db.close()


def cmd_export_csv(args):
    """导出CSV报告"""
    db = SessionLocal()
    try:
        exporter = ReportExporter(db)
        files = exporter.export_csv(
            args.batch_id,
            include_raw_data=not args.no_raw_data,
            filename=args.output
        )
        print(f"CSV报告已导出:")
        for name, path in files.items():
            print(f"  {name}: {path}")
    finally:
        db.close()


def cmd_export_summary(args):
    """导出所有批次汇总"""
    db = SessionLocal()
    try:
        exporter = ReportExporter(db)
        filepath = exporter.export_summary_csv(args.output)
        print(f"批次汇总已导出: {filepath}")
    finally:
        db.close()


def cmd_import_remarks(args):
    """从CSV导入备注"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        file_path = args.file or os.path.join(SAMPLE_DATA_DIR, "sample_remarks.csv")
        print(f"导入备注: {file_path}")
        success, stats, errors = batch_manager.import_remarks_from_csv(args.batch_id, file_path)

        if not success:
            print(f"导入失败，错误信息:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        total = stats.get("total", 0)
        imported = stats.get("imported", 0)
        skipped = stats.get("skipped", 0)
        failed = stats.get("failed", 0)
        print(f"备注导入完成: 总计 {total} 条 (导入 {imported}, 跳过 {skipped}, 失败 {failed})")

        if errors:
            print(f"详细信息:")
            for err in errors:
                print(f"  - {err}")
    finally:
        db.close()


def cmd_add_remark(args):
    """单条追加备注"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        success, remark, errors = batch_manager.add_remark(
            batch_id=args.batch_id,
            content=args.content,
            anomaly_id=args.anomaly_id,
            operator=args.operator or "system",
            remark_type=args.remark_type or "general"
        )

        if not success:
            print(f"添加备注失败:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)

        print(f"备注添加成功: ID={remark.id}, 类型={remark.remark_type}, 操作人={remark.operator}")
        print(f"  内容: {remark.content}")
    finally:
        db.close()


def cmd_list_remarks(args):
    """查看备注列表"""
    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)

        if args.all:
            remarks = batch_manager.get_all_remarks(args.batch_id)
        else:
            remarks = batch_manager.get_remarks(args.batch_id, args.anomaly_id)

        scope = "全部" if args.all else ("异常级" if args.anomaly_id else "批次级")
        print(f"批次 {args.batch_id} {scope}备注列表 (共 {len(remarks)} 条):")
        for r in remarks:
            anomaly_info = f", 异常ID={r.anomaly_id}" if r.anomaly_id else ""
            import_info = f", import_key={r.import_key}" if r.import_key else ""
            source_info = f", 来源={r.source}" if r.source else ""
            print(f"  ID={r.id} | 类型={r.remark_type} | 操作人={r.operator}{anomaly_info}{import_info}{source_info}")
            print(f"      时间: {r.created_at}")
            print(f"      内容: {r.content}")
    finally:
        db.close()


def cmd_run_full_flow(args):
    """运行完整演示流程"""
    print_separator("泵房巡检异常分析工具 - 完整演示流程")

    # Step 1: 初始化数据库
    print_separator("Step 1: 初始化数据库")
    init_db()
    print("数据库初始化完成")

    db = SessionLocal()
    try:
        batch_manager = BatchManager(db)
        rule_manager = RuleManager(db)
        exporter = ReportExporter(db)

        # Step 2: 导入设备台账
        print_separator("Step 2: 导入设备台账")
        equipment_file = os.path.join(SAMPLE_DATA_DIR, "equipment_ledger.csv")
        success, count, errors = batch_manager.import_equipment_ledger(equipment_file)
        print(f"成功导入 {count} 条设备台账记录")

        # Step 3: 设置规则版本
        print_separator("Step 3: 设置规则版本")
        rule_manager.set_active_version("v2")
        active_rule = rule_manager.get_active_version()
        print(f"当前使用规则版本: {active_rule.version} - {active_rule.description}")

        # Step 4: 创建批次
        print_separator("Step 4: 创建分析批次")
        batch = batch_manager.create_batch(
            batch_name=args.batch_name or "2026年6月上旬泵房巡检数据分析",
            rule_version="v2",
            source_file="sample_data/sensor_readings_with_anomalies.csv",
            notes="完整演示流程批次"
        )
        print(f"批次创建成功: ID={batch.id}")

        # Step 5: 导入传感器读数（含异常）
        print_separator("Step 5: 导入传感器读数")
        readings_file = os.path.join(SAMPLE_DATA_DIR, "sensor_readings_with_anomalies.csv")
        success, unmapped, tz_issues = batch_manager.import_sensor_readings(batch.id, readings_file)
        batch = batch_manager.get_batch(batch.id)
        print(f"成功导入 {batch.total_records} 条记录")
        if unmapped:
            print(f"未映射列: {unmapped}")
        if tz_issues:
            print(f"时区问题 (共 {len(tz_issues)} 条):")
            for issue in tz_issues:
                print(f"  - {issue}")

        # Step 6: 导入巡检班次
        print_separator("Step 6: 导入巡检班次")
        shifts_file = os.path.join(SAMPLE_DATA_DIR, "inspection_shifts.csv")
        success, stats, errors = batch_manager.import_inspection_shifts(batch.id, shifts_file)
        total = stats.get("total", 0)
        inserted = stats.get("inserted", 0)
        updated = stats.get("updated", 0)
        print(f"巡检班次导入完成: 总计 {total} 条 (新增 {inserted}, 更新 {updated})")

        # Step 7: 异常检测
        print_separator("Step 7: 运行异常检测")
        rule_config = rule_manager.get_rule_config("v2")
        count, anomalies = batch_manager.run_detection(batch.id, rule_config)
        batch = batch_manager.get_batch(batch.id)
        print(f"检测完成，共发现 {batch.anomaly_count} 条异常:")
        summary = batch_manager.get_anomaly_summary(batch.id)
        for code, data in summary.items():
            print(f"  {data['name']} ({code}): {data['count']} 条")

        # Step 8: 人工复核一条异常（标记为误报）
        print_separator("Step 8: 人工复核异常")
        anomalies = batch_manager.get_batch_anomalies(batch.id, reviewed=False)
        if anomalies:
            target_anomaly = anomalies[0]
            print(f"标记异常 #{target_anomaly.id} 为误报...")
            batch_manager.review_anomaly(
                target_anomaly.id,
                "false_positive",
                "经核实为传感器临时波动，非真实异常",
                "张三"
            )
            batch = batch_manager.get_batch(batch.id)
            print(f"复核完成，已复核 {batch.reviewed_count}/{batch.anomaly_count} 条")

        # Step 9: 回滚该复核
        print_separator("Step 9: 回滚复核结果")
        batch_manager.rollback_review(target_anomaly.id)
        batch = batch_manager.get_batch(batch.id)
        print(f"回滚完成，已复核 {batch.reviewed_count}/{batch.anomaly_count} 条")

        # Step 10: 复核第二条异常（确认真实异常）
        print_separator("Step 10: 复核第二条异常并确认真实异常")
        anomalies = batch_manager.get_batch_anomalies(batch.id, reviewed=False)
        if len(anomalies) >= 2:
            target_anomaly2 = anomalies[1]
            print(f"标记异常 #{target_anomaly2.id} 为确认异常...")
            batch_manager.review_anomaly(
                target_anomaly2.id,
                "confirmed",
                "经现场核实，该异常属实，已安排维修",
                "李四"
            )
            batch = batch_manager.get_batch(batch.id)
            print(f"复核完成，已复核 {batch.reviewed_count}/{batch.anomaly_count} 条")

        # Step 11: 导出报告
        print_separator("Step 11: 导出分析报告")
        html_path = exporter.export_html(batch.id, include_raw_data=True)
        csv_files = exporter.export_csv(batch.id, include_raw_data=True)
        summary_path = exporter.export_summary_csv()

        print(f"HTML报告: {html_path}")
        print(f"CSV报告:")
        for name, path in csv_files.items():
            print(f"  {name}: {path}")
        print(f"批次汇总: {summary_path}")

        # Step 12: 测试错误场景 - 缺少设备编号列
        print_separator("Step 12: 测试错误场景 - 缺少设备编号列")
        batch2 = batch_manager.create_batch(
            batch_name="测试_缺少设备编号列",
            rule_version="v2",
            source_file="sample_data/sensor_readings_missing_device_id.csv"
        )
        missing_file = os.path.join(SAMPLE_DATA_DIR, "sensor_readings_missing_device_id.csv")
        success, unmapped, errors = batch_manager.import_sensor_readings(batch2.id, missing_file)
        if not success:
            print(f"成功捕获错误: {errors[0]}")

        # Step 13: 测试错误场景 - 错误时区
        print_separator("Step 13: 测试错误场景 - 错误时区")
        batch3 = batch_manager.create_batch(
            batch_name="测试_错误时区",
            rule_version="v2",
            source_file="sample_data/sensor_readings_wrong_timezone.csv"
        )
        tz_file = os.path.join(SAMPLE_DATA_DIR, "sensor_readings_wrong_timezone.csv")
        success, unmapped, tz_issues = batch_manager.import_sensor_readings(batch3.id, tz_file, skip_validation=True)
        if tz_issues:
            print(f"成功识别时区问题 (共 {len(tz_issues)} 条):")
            for issue in tz_issues[:3]:
                print(f"  - 行{issue.get('row')}: {issue.get('message')}")
        count, anomalies = batch_manager.run_detection(batch3.id, rule_config)
        print(f"该批次检测到 {count} 条异常")

        # Step 14: 显示复核历史
        print_separator("Step 14: 显示复核历史")
        review_history = batch_manager.get_review_history(batch.id)
        print(f"批次 {batch.id} 复核历史 (共 {len(review_history)} 条):")
        for record in review_history:
            print(f"  {record.reviewed_at} | 异常#{record.anomaly_id} | "
                  f"{record.action} | {record.review_result} | {record.reviewed_by}")

        # Final: 显示所有批次汇总
        print_separator("所有批次汇总")
        batches = batch_manager.get_all_batches()
        for b in batches:
            print(f"  ID={b.id} | {b.batch_name} | 规则={b.rule_version} | "
                  f"状态={b.status} | 记录={b.total_records} | 异常={b.anomaly_count} | "
                  f"已复核={b.reviewed_count}")

        print_separator("演示流程完成")
        print("\n预期异常数量说明:")
        print("  - 批次1 (主批次): 约 12-13 条异常")
        print("    * 水压突降: 2 条")
        print("    * 长时间离线: 2 条")
        print("    * 读数倒退: 1 条")
        print("    * 重复上报: 2 条")
        print("    * 未登记设备: 2 条 (PUMP-999)")
        print("    * 同时刻不同读数: 2 条")
        print("    * 水压超限: 2 条")
        print("  - 批次2 (缺少设备编号): 导入失败，缺少必填列")
        print("  - 批次3 (错误时区): 时区问题已识别，无异常")
        print("\n重启后验证: 批次、复核历史、回滚结果、规则版本、导出汇总均保存在数据库中，重启后依然一致。")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="小区泵房巡检异常分析工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例命令:
  # 初始化数据库
  python main.py init-db

  # 导入设备台账
  python main.py import-equipment

  # 创建批次
  python main.py create-batch --name "2026年6月数据分析"

  # 导入传感器读数
  python main.py import-readings --batch-id 1

  # 运行异常检测
  python main.py detect --batch-id 1

  # 列出异常
  python main.py list-anomalies --batch-id 1

  # 复核异常
  python main.py review --anomaly-id 1 --result false_positive --notes "传感器波动"

  # 回滚复核
  python main.py rollback --anomaly-id 1

  # 导入备注（从CSV）
  python main.py import-remarks --batch-id 1

  # 追加单条备注（批次级）
  python main.py add-remark --batch-id 1 --content "2026年6月8日停泵检修" --operator "张三" --remark-type maintenance

  # 追加单条备注（异常级）
  python main.py add-remark --batch-id 1 --anomaly-id 1 --content "经核实为传感器临时波动" --operator "李四"

  # 查看批次级备注
  python main.py list-remarks --batch-id 1

  # 查看异常级备注
  python main.py list-remarks --batch-id 1 --anomaly-id 1

  # 查看全部备注
  python main.py list-remarks --batch-id 1 --all

  # 导出HTML报告
  python main.py export-html --batch-id 1

  # 导出CSV报告
  python main.py export-csv --batch-id 1

  # 运行完整演示流程
  python main.py run-full-flow
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # init-db
    p = subparsers.add_parser("init-db", help="初始化数据库")
    p.set_defaults(func=cmd_init_db)

    # import-equipment
    p = subparsers.add_parser("import-equipment", help="导入设备台账")
    p.add_argument("--file", help="设备台账文件路径")
    p.add_argument("--skip-validation", action="store_true", help="跳过校验")
    p.set_defaults(func=cmd_import_equipment)

    # list-equipment
    p = subparsers.add_parser("list-equipment", help="列出设备台账")
    p.set_defaults(func=cmd_list_equipment)

    # create-batch
    p = subparsers.add_parser("create-batch", help="创建分析批次")
    p.add_argument("--name", required=True, help="批次名称")
    p.add_argument("--rule-version", help="规则版本，默认使用当前激活版本")
    p.add_argument("--source", help="源文件路径")
    p.add_argument("--notes", help="备注")
    p.set_defaults(func=cmd_create_batch)

    # import-readings
    p = subparsers.add_parser("import-readings", help="导入传感器读数")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--file", help="传感器读数文件路径")
    p.add_argument("--skip-validation", action="store_true", help="跳过校验")
    p.set_defaults(func=cmd_import_readings)

    # import-shifts
    p = subparsers.add_parser("import-shifts", help="导入巡检班次")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--file", help="巡检班次文件路径")
    p.set_defaults(func=cmd_import_shifts)

    # detect
    p = subparsers.add_parser("detect", help="运行异常检测")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.set_defaults(func=cmd_detect)

    # list-batches
    p = subparsers.add_parser("list-batches", help="列出所有批次")
    p.set_defaults(func=cmd_list_batches)

    # list-anomalies
    p = subparsers.add_parser("list-anomalies", help="列出批次异常")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--reviewed", choices=["yes", "no"], help="按复核状态过滤")
    p.set_defaults(func=cmd_list_anomalies)

    # review
    p = subparsers.add_parser("review", help="复核异常")
    p.add_argument("--anomaly-id", type=int, required=True, help="异常ID")
    p.add_argument("--result", required=True, choices=["confirmed", "false_positive", "other"], help="复核结果")
    p.add_argument("--notes", help="复核备注")
    p.add_argument("--reviewer", default="admin", help="复核人")
    p.set_defaults(func=cmd_review)

    # rollback
    p = subparsers.add_parser("rollback", help="回滚复核结果")
    p.add_argument("--anomaly-id", type=int, required=True, help="异常ID")
    p.set_defaults(func=cmd_rollback)

    # list-rules
    p = subparsers.add_parser("list-rules", help="列出所有规则版本")
    p.set_defaults(func=cmd_list_rules)

    # use-rule
    p = subparsers.add_parser("use-rule", help="设置使用的规则版本")
    p.add_argument("--version", required=True, help="规则版本号")
    p.set_defaults(func=cmd_use_rule)

    # export-html
    p = subparsers.add_parser("export-html", help="导出HTML报告")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--output", help="输出文件名")
    p.add_argument("--no-raw-data", action="store_true", help="不包含原始数据")
    p.set_defaults(func=cmd_export_html)

    # export-csv
    p = subparsers.add_parser("export-csv", help="导出CSV报告")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--output", help="输出文件名前缀")
    p.add_argument("--no-raw-data", action="store_true", help="不包含原始数据")
    p.set_defaults(func=cmd_export_csv)

    # export-summary
    p = subparsers.add_parser("export-summary", help="导出所有批次汇总")
    p.add_argument("--output", help="输出文件名")
    p.set_defaults(func=cmd_export_summary)

    # import-remarks
    p = subparsers.add_parser("import-remarks", help="从CSV导入备注")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--file", help="备注CSV文件路径，默认使用 sample_data/sample_remarks.csv")
    p.set_defaults(func=cmd_import_remarks)

    # add-remark
    p = subparsers.add_parser("add-remark", help="单条追加备注")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--anomaly-id", type=int, help="异常ID（异常级备注），不填则为批次级备注")
    p.add_argument("--content", required=True, help="备注内容")
    p.add_argument("--operator", help="操作人，默认 system")
    p.add_argument("--remark-type", help="备注类型，默认 general，可选: maintenance, sensor_replacement, manual_entry, general")
    p.set_defaults(func=cmd_add_remark)

    # list-remarks
    p = subparsers.add_parser("list-remarks", help="查看备注列表")
    p.add_argument("--batch-id", type=int, required=True, help="批次ID")
    p.add_argument("--anomaly-id", type=int, help="按异常ID过滤（只看该异常的备注）")
    p.add_argument("--all", action="store_true", help="显示全部备注（批次级+异常级）")
    p.set_defaults(func=cmd_list_remarks)

    # run-full-flow
    p = subparsers.add_parser("run-full-flow", help="运行完整演示流程")
    p.add_argument("--batch-name", help="批次名称")
    p.set_defaults(func=cmd_run_full_flow)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
