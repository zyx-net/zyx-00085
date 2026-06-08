import pandas as pd
import os
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from jinja2 import Template
from .models import Batch, Anomaly, SensorReading, ReviewRecord, Remark


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>泵房巡检异常分析报告 - {{ batch.batch_name }}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Microsoft YaHei', Arial, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-bottom: 20px; }
        .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .summary-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; }
        .summary-card.warning { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .summary-card.success { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
        .summary-card.danger { background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); }
        .summary-card h3 { font-size: 14px; opacity: 0.9; margin-bottom: 10px; }
        .summary-card .value { font-size: 32px; font-weight: bold; }
        .summary-card .label { font-size: 12px; opacity: 0.8; margin-top: 5px; }
        h2 { color: #34495e; margin: 25px 0 15px; padding-left: 10px; border-left: 4px solid #3498db; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        th { background: #34495e; color: white; padding: 12px; text-align: left; font-weight: 500; }
        td { padding: 12px; border-bottom: 1px solid #ecf0f1; }
        tr:hover { background: #f8f9fa; }
        .severity-critical { color: #e74c3c; font-weight: bold; }
        .severity-high { color: #e67e22; font-weight: bold; }
        .severity-medium { color: #f39c12; font-weight: bold; }
        .severity-low { color: #27ae60; font-weight: bold; }
        .status-confirmed { background: #d4edda; color: #155724; padding: 4px 10px; border-radius: 4px; }
        .status-false-positive { background: #f8d7da; color: #721c24; padding: 4px 10px; border-radius: 4px; }
        .status-pending { background: #fff3cd; color: #856404; padding: 4px 10px; border-radius: 4px; }
        .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; background: #f8f9fa; padding: 15px; border-radius: 8px; }
        .info-item { display: flex; }
        .info-item .label { font-weight: bold; color: #7f8c8d; width: 120px; }
        .anomaly-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .anomaly-type-card { background: #fff; border: 1px solid #e1e8ed; border-radius: 8px; padding: 15px; }
        .anomaly-type-card h4 { color: #2c3e50; margin-bottom: 10px; }
        .anomaly-type-card .stats { display: flex; justify-content: space-between; font-size: 14px; }
        .footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #ecf0f1; color: #7f8c8d; font-size: 12px; text-align: center; }
        .raw-data { background: #f8f9fa; padding: 10px; font-family: monospace; font-size: 12px; border-radius: 4px; margin-top: 5px; white-space: pre-wrap; word-break: break-all; }
        .remark-type-badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; color: white; }
        .remark-type-maintenance { background: #e67e22; }
        .remark-type-sensor_replacement { background: #9b59b6; }
        .remark-type-manual_entry { background: #1abc9c; }
        .remark-type-general { background: #95a5a6; }
        .remark-list { margin-top: 10px; }
        .remark-item { background: #f8f9fa; padding: 10px; border-radius: 4px; margin-bottom: 8px; border-left: 3px solid #3498db; }
        .remark-item .remark-header { font-size: 12px; color: #7f8c8d; margin-bottom: 5px; }
        .remark-item .remark-content { font-size: 14px; color: #2c3e50; }
        .remark-anomaly-link { color: #3498db; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>泵房巡检异常分析报告</h1>

        <div class="info-grid">
            <div class="info-item"><span class="label">批次名称:</span> {{ batch.batch_name }}</div>
            <div class="info-item"><span class="label">批次ID:</span> {{ batch.id }}</div>
            <div class="info-item"><span class="label">规则版本:</span> {{ batch.rule_version }}</div>
            <div class="info-item"><span class="label">导入时间:</span> {{ batch.import_time }}</div>
            <div class="info-item"><span class="label">状态:</span> {{ batch.status }}</div>
            <div class="info-item"><span class="label">数据源:</span> {{ batch.source_file }}</div>
        </div>

        <h2>概览统计</h2>
        <div class="summary">
            <div class="summary-card">
                <h3>导入记录数</h3>
                <div class="value">{{ batch.total_records }}</div>
                <div class="label">条传感器读数</div>
            </div>
            <div class="summary-card warning">
                <h3>异常总数</h3>
                <div class="value">{{ batch.anomaly_count }}</div>
                <div class="label">条异常记录</div>
            </div>
            <div class="summary-card success">
                <h3>已复核</h3>
                <div class="value">{{ batch.reviewed_count }}</div>
                <div class="label">条已处理</div>
            </div>
            <div class="summary-card danger">
                <h3>待复核</h3>
                <div class="value">{{ batch.anomaly_count - batch.reviewed_count }}</div>
                <div class="label">条待处理</div>
            </div>
        </div>

        {% if anomaly_summary %}
        <h2>异常类型分布</h2>
        <div class="anomaly-summary">
            {% for code, data in anomaly_summary.items() %}
            <div class="anomaly-type-card">
                <h4>{{ data.name }} ({{ code }})</h4>
                <div class="stats"><span>总数:</span><strong>{{ data.count }}</strong></div>
                <div class="stats"><span>已复核:</span><strong>{{ data.reviewed }}</strong></div>
                <div class="stats"><span>确认异常:</span><strong class="severity-high">{{ data.confirmed }}</strong></div>
                <div class="stats"><span>误报:</span><strong class="severity-low">{{ data.false_positive }}</strong></div>
            </div>
            {% endfor %}
        </div>
        {% endif %}

        {% if review_history %}
        <h2>复核历史记录</h2>
        <table>
            <thead>
                <tr>
                    <th>时间</th>
                    <th>异常ID</th>
                    <th>操作</th>
                    <th>结果</th>
                    <th>复核人</th>
                    <th>备注</th>
                </tr>
            </thead>
            <tbody>
                {% for record in review_history %}
                <tr>
                    <td>{{ record.reviewed_at }}</td>
                    <td>#{{ record.anomaly_id }}</td>
                    <td>{{ '回滚' if record.action == 'rollback' else '复核' }}</td>
                    <td>{{ record.review_result }}</td>
                    <td>{{ record.reviewed_by }}</td>
                    <td>{{ record.review_notes or '-' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}

        {% if all_remarks %}
        <h2>交接备注历史</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>时间</th>
                    <th>关联对象</th>
                    <th>类型</th>
                    <th>操作人</th>
                    <th>备注内容</th>
                    <th>来源</th>
                </tr>
            </thead>
            <tbody>
                {% for r in all_remarks %}
                <tr>
                    <td>#{{ r.id }}</td>
                    <td>{{ r.created_at }}</td>
                    <td>
                        {% if r.anomaly_id %}
                        <span class="remark-anomaly-link">异常 #{{ r.anomaly_id }}</span>
                        {% else %}
                        批次备注
                        {% endif %}
                    </td>
                    <td><span class="remark-type-badge remark-type-{{ r.remark_type }}">{{ r.remark_type }}</span></td>
                    <td>{{ r.operator }}</td>
                    <td>{{ r.content }}</td>
                    <td>{{ r.source or '-' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        {% if batch_remarks %}
        <h3>批次级备注</h3>
        <div class="remark-list">
            {% for r in batch_remarks %}
            <div class="remark-item">
                <div class="remark-header">
                    <span class="remark-type-badge remark-type-{{ r.remark_type }}">{{ r.remark_type }}</span>
                    {{ r.created_at }} | {{ r.operator }}
                    {% if r.previous_remark_id %} | 前序ID: #{{ r.previous_remark_id }}{% endif %}
                </div>
                <div class="remark-content">{{ r.content }}</div>
                {% if r.source %}<div class="remark-header">来源: {{ r.source }}</div>{% endif %}
            </div>
            {% endfor %}
        </div>
        {% endif %}
        {% endif %}

        <h2>异常明细</h2>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>异常类型</th>
                    <th>严重程度</th>
                    <th>设备编号</th>
                    <th>读数时间</th>
                    <th>描述</th>
                    <th>状态</th>
                    <th>原始行号</th>
                </tr>
            </thead>
            <tbody>
                {% for anomaly in anomalies %}
                <tr>
                    <td>#{{ anomaly.id }}</td>
                    <td>{{ anomaly.anomaly_type }}<br><small>{{ anomaly.anomaly_code }}</small></td>
                    <td><span class="severity-{{ anomaly.severity }}">{{ anomaly.severity }}</span></td>
                    <td>{{ anomaly.device_id }}</td>
                    <td>{{ anomaly.reading_time }}</td>
                    <td>
                        {{ anomaly.description }}
                        {% if anomaly_remarks.get(anomaly.id) %}
                        <div class="remark-list">
                            {% for r in anomaly_remarks[anomaly.id] %}
                            <div class="remark-item">
                                <div class="remark-header">
                                    <span class="remark-type-badge remark-type-{{ r.remark_type }}">{{ r.remark_type }}</span>
                                    {{ r.created_at }} | {{ r.operator }}
                                </div>
                                <div class="remark-content">{{ r.content }}</div>
                            </div>
                            {% endfor %}
                        </div>
                        {% endif %}
                    </td>
                    <td>
                        {% if not anomaly.is_reviewed %}
                        <span class="status-pending">待复核</span>
                        {% elif anomaly.review_result == 'confirmed' %}
                        <span class="status-confirmed">确认异常</span>
                        {% elif anomaly.review_result == 'false_positive' %}
                        <span class="status-false-positive">误报</span>
                        {% else %}
                        {{ anomaly.review_result }}
                        {% endif %}
                    </td>
                    <td>{% if anomaly.reading %}行{{ anomaly.reading.raw_row_index }}{% else %}-{% endif %}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        {% if include_raw_data and readings %}
        <h2>原始导入数据</h2>
        <table>
            <thead>
                <tr>
                    <th>原始行号</th>
                    <th>设备编号</th>
                    <th>读数时间</th>
                    <th>水压(MPa)</th>
                    <th>流量(m³/h)</th>
                    <th>温度(℃)</th>
                    <th>巡检员</th>
                    <th>原始数据</th>
                </tr>
            </thead>
            <tbody>
                {% for reading in readings %}
                <tr>
                    <td>{{ reading.raw_row_index }}</td>
                    <td>{{ reading.device_id }}</td>
                    <td>{{ reading.reading_time }}</td>
                    <td>{{ reading.water_pressure or '-' }}</td>
                    <td>{{ reading.flow_rate or '-' }}</td>
                    <td>{{ reading.temperature or '-' }}</td>
                    <td>{{ reading.inspector or '-' }}</td>
                    <td><div class="raw-data">{{ reading.raw_data }}</div></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}

        <div class="footer">
            报告生成时间: {{ report_time }} | 泵房巡检异常分析工具 v1.0
        </div>
    </div>
</body>
</html>
"""


class ReportExporter:
    def __init__(self, db_session: Session, output_dir: Optional[str] = None):
        self.db = db_session
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "reports"
            )
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def export_html(self, batch_id: int, include_raw_data: bool = True, filename: Optional[str] = None) -> str:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise ValueError("批次不存在")

        anomalies = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id).order_by(Anomaly.id).all()
        readings = self.db.query(SensorReading).filter(SensorReading.batch_id == batch_id).order_by(SensorReading.raw_row_index).all() if include_raw_data else []
        review_history = self.db.query(ReviewRecord).filter(ReviewRecord.batch_id == batch_id).order_by(ReviewRecord.reviewed_at.desc()).all()

        all_remarks = self.db.query(Remark).filter(Remark.batch_id == batch_id).order_by(Remark.created_at.desc()).all()
        batch_remarks = [r for r in all_remarks if r.anomaly_id is None]
        anomaly_remarks = {}
        for r in all_remarks:
            if r.anomaly_id:
                if r.anomaly_id not in anomaly_remarks:
                    anomaly_remarks[r.anomaly_id] = []
                anomaly_remarks[r.anomaly_id].append(r)

        anomaly_summary = self._get_anomaly_summary(batch_id)

        template = Template(HTML_TEMPLATE)
        html_content = template.render(
            batch=batch,
            anomalies=anomalies,
            readings=readings,
            review_history=review_history,
            all_remarks=all_remarks,
            batch_remarks=batch_remarks,
            anomaly_remarks=anomaly_remarks,
            anomaly_summary=anomaly_summary,
            include_raw_data=include_raw_data,
            report_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        if not filename:
            safe_name = "".join(c for c in batch.batch_name if c.isalnum() or c in ("-", "_"))
            filename = f"batch_{batch_id}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"

        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        return filepath

    def export_csv(self, batch_id: int, include_raw_data: bool = True, filename: Optional[str] = None) -> Dict[str, str]:
        batch = self.db.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise ValueError("批次不存在")

        if not filename:
            safe_name = "".join(c for c in batch.batch_name if c.isalnum() or c in ("-", "_"))
            filename = f"batch_{batch_id}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        files = {}

        anomalies = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id).order_by(Anomaly.id).all()
        anomaly_data = []
        for a in anomalies:
            anomaly_data.append({
                "异常ID": a.id,
                "异常类型": a.anomaly_type,
                "异常代码": a.anomaly_code,
                "严重程度": a.severity,
                "设备编号": a.device_id,
                "读数时间": a.reading_time,
                "描述": a.description,
                "预期值": a.expected_value,
                "实际值": a.actual_value,
                "检测时间": a.detected_time,
                "是否复核": "是" if a.is_reviewed else "否",
                "复核结果": a.review_result or "",
                "复核备注": a.review_notes or "",
                "复核人": a.reviewed_by or "",
                "复核时间": a.reviewed_at or "",
                "是否回滚": "是" if a.is_rollback else "否",
                "原始行号": a.reading.raw_row_index if a.reading else ""
            })

        if anomaly_data:
            df = pd.DataFrame(anomaly_data)
            anomaly_file = os.path.join(self.output_dir, f"{filename}_anomalies.csv")
            df.to_csv(anomaly_file, index=False, encoding="utf-8-sig")
            files["anomalies"] = anomaly_file

        review_history = self.db.query(ReviewRecord).filter(ReviewRecord.batch_id == batch_id).order_by(ReviewRecord.reviewed_at.desc()).all()
        review_data = []
        for r in review_history:
            review_data.append({
                "记录ID": r.id,
                "异常ID": r.anomaly_id,
                "操作类型": "回滚" if r.action == "rollback" else "复核",
                "复核结果": r.review_result,
                "复核备注": r.review_notes or "",
                "复核人": r.reviewed_by or "",
                "复核时间": r.reviewed_at
            })

        if review_data:
            df = pd.DataFrame(review_data)
            review_file = os.path.join(self.output_dir, f"{filename}_review_history.csv")
            df.to_csv(review_file, index=False, encoding="utf-8-sig")
            files["review_history"] = review_file

        remarks = self.db.query(Remark).filter(Remark.batch_id == batch_id).order_by(Remark.created_at.desc()).all()
        remark_data = []
        for r in remarks:
            remark_data.append({
                "备注ID": r.id,
                "批次ID": r.batch_id,
                "异常ID": r.anomaly_id or "",
                "备注类型": r.remark_type,
                "备注内容": r.content,
                "操作人": r.operator,
                "创建时间": r.created_at,
                "来源": r.source or "",
                "导入Key": r.import_key or "",
                "前序备注ID": r.previous_remark_id or ""
            })

        if remark_data:
            df = pd.DataFrame(remark_data)
            remark_file = os.path.join(self.output_dir, f"{filename}_remarks.csv")
            df.to_csv(remark_file, index=False, encoding="utf-8-sig")
            files["remarks"] = remark_file

        if include_raw_data:
            readings = self.db.query(SensorReading).filter(SensorReading.batch_id == batch_id).order_by(SensorReading.raw_row_index).all()
            reading_data = []
            for r in readings:
                reading_data.append({
                    "记录ID": r.id,
                    "原始行号": r.raw_row_index,
                    "设备编号": r.device_id,
                    "读数时间": r.reading_time,
                    "水压(MPa)": r.water_pressure,
                    "流量(m³/h)": r.flow_rate,
                    "温度(℃)": r.temperature,
                    "状态": r.status or "",
                    "巡检员": r.inspector or "",
                    "时区": r.time_zone,
                    "原始数据": r.raw_data
                })

            if reading_data:
                df = pd.DataFrame(reading_data)
                reading_file = os.path.join(self.output_dir, f"{filename}_raw_data.csv")
                df.to_csv(reading_file, index=False, encoding="utf-8-sig")
                files["raw_data"] = reading_file

        summary_data = [{
            "批次ID": batch.id,
            "批次名称": batch.batch_name,
            "规则版本": batch.rule_version,
            "导入时间": batch.import_time,
            "状态": batch.status,
            "导入记录数": batch.total_records,
            "异常总数": batch.anomaly_count,
            "已复核数": batch.reviewed_count,
            "待复核数": batch.anomaly_count - batch.reviewed_count,
            "数据源": batch.source_file,
            "备注": batch.notes or ""
        }]
        df = pd.DataFrame(summary_data)
        summary_file = os.path.join(self.output_dir, f"{filename}_summary.csv")
        df.to_csv(summary_file, index=False, encoding="utf-8-sig")
        files["summary"] = summary_file

        return files

    def export_summary_csv(self, filename: Optional[str] = None) -> str:
        batches = self.db.query(Batch).order_by(Batch.import_time.desc()).all()

        data = []
        for batch in batches:
            anomaly_summary = self._get_anomaly_summary(batch.id)
            data.append({
                "批次ID": batch.id,
                "批次名称": batch.batch_name,
                "规则版本": batch.rule_version,
                "导入时间": batch.import_time,
                "状态": batch.status,
                "导入记录数": batch.total_records,
                "异常总数": batch.anomaly_count,
                "已复核数": batch.reviewed_count,
                "待复核数": batch.anomaly_count - batch.reviewed_count,
                "异常类型明细": str(anomaly_summary),
                "数据源": batch.source_file
            })

        df = pd.DataFrame(data)
        if not filename:
            filename = f"export_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        filepath = os.path.join(self.output_dir, filename)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return filepath

    def _get_anomaly_summary(self, batch_id: int) -> Dict:
        anomalies = self.db.query(Anomaly).filter(Anomaly.batch_id == batch_id).all()
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

    def export_rule_comparison_csv(self, comparison_data: Dict, filename_prefix: Optional[str] = None) -> Dict[str, str]:
        meta = comparison_data["meta"]
        totals = comparison_data["totals"]
        v1 = meta["rule_version_1"]
        v2 = meta["rule_version_2"]

        if not filename_prefix:
            safe_name = "".join(c for c in meta["batch_name"] if c.isalnum() or c in ("-", "_"))
            filename_prefix = f"comparison_batch{meta['batch_id']}_{safe_name}_{v1}_vs_{v2}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        files = {}

        summary_data = [{
            "批次ID": meta["batch_id"],
            "批次名称": meta["batch_name"],
            "规则版本1": v1,
            "规则版本2": v2,
            "对比时间": meta["comparison_time"],
            "巡检记录总数": meta["total_records"],
            f"版本{v1}异常总数": totals["version1_total"],
            f"版本{v2}异常总数": totals["version2_total"],
            "异常数差异": totals["difference"],
            f"仅在版本{v1}出现": totals["only_in_version1"],
            f"仅在版本{v2}出现": totals["only_in_version2"],
            "两个版本都出现": totals["in_both_versions"],
            "严重级别变化数": totals["severity_changes"],
            "数据源文件": meta["source_file"],
            f"版本{v1}检测来源": meta["detection_source_v1"],
            f"版本{v2}检测来源": meta["detection_source_v2"],
            f"版本{v1}是否新检测": "是" if meta["detection_newly_run_v1"] else "否",
            f"版本{v2}是否新检测": "是" if meta["detection_newly_run_v2"] else "否",
        }]
        df = pd.DataFrame(summary_data)
        summary_file = os.path.join(self.output_dir, f"{filename_prefix}_overall_summary.csv")
        df.to_csv(summary_file, index=False, encoding="utf-8-sig")
        files["overall_summary"] = summary_file

        type_codes = set(comparison_data["by_type_v1"].keys()) | set(comparison_data["by_type_v2"].keys())
        type_comparison_data = []
        for code in sorted(type_codes):
            t1 = comparison_data["by_type_v1"].get(code, {})
            t2 = comparison_data["by_type_v2"].get(code, {})
            count1 = t1.get("数量", 0)
            count2 = t2.get("数量", 0)
            type_comparison_data.append({
                "异常类型": t1.get("异常类型", t2.get("异常类型", "")),
                "异常代码": code,
                f"版本{v1}数量": count1,
                f"版本{v2}数量": count2,
                "数量差异": count2 - count1,
                f"版本{v1}严重级别分布": str(t1.get("严重级别分布", {})),
                f"版本{v2}严重级别分布": str(t2.get("严重级别分布", {})),
            })
        if type_comparison_data:
            df = pd.DataFrame(type_comparison_data)
            type_file = os.path.join(self.output_dir, f"{filename_prefix}_by_type.csv")
            df.to_csv(type_file, index=False, encoding="utf-8-sig")
            files["by_type"] = type_file

        sev_levels = ["critical", "high", "medium", "low"]
        sev_names = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}
        sev_comparison_data = []
        for sev in sev_levels:
            count1 = comparison_data["by_severity_v1"].get(sev, 0)
            count2 = comparison_data["by_severity_v2"].get(sev, 0)
            sev_comparison_data.append({
                "严重级别": sev_names.get(sev, sev),
                "严重级别代码": sev,
                f"版本{v1}数量": count1,
                f"版本{v2}数量": count2,
                "数量差异": count2 - count1,
            })
        df = pd.DataFrame(sev_comparison_data)
        sev_file = os.path.join(self.output_dir, f"{filename_prefix}_by_severity.csv")
        df.to_csv(sev_file, index=False, encoding="utf-8-sig")
        files["by_severity"] = sev_file

        if comparison_data["severity_changes"]:
            changes_data = []
            for change in comparison_data["severity_changes"]:
                changes_data.append({
                    "异常类型": change["anomaly_type"],
                    "异常代码": change["anomaly_code"],
                    "设备编号": change["device_id"],
                    "读数时间": change["reading_time"],
                    f"版本{v1}严重级别": sev_names.get(change["severity_v1"], change["severity_v1"]),
                    f"版本{v2}严重级别": sev_names.get(change["severity_v2"], change["severity_v2"]),
                    "变化方向": f"{sev_names.get(change['severity_v1'], change['severity_v1'])} -> {sev_names.get(change['severity_v2'], change['severity_v2'])}",
                    "描述": change["description"],
                })
            df = pd.DataFrame(changes_data)
            changes_file = os.path.join(self.output_dir, f"{filename_prefix}_severity_changes.csv")
            df.to_csv(changes_file, index=False, encoding="utf-8-sig")
            files["severity_changes"] = changes_file

        if comparison_data["only_in_version1"]:
            df = pd.DataFrame(comparison_data["only_in_version1"])
            only_v1_file = os.path.join(self.output_dir, f"{filename_prefix}_only_in_{v1}.csv")
            df.to_csv(only_v1_file, index=False, encoding="utf-8-sig")
            files[f"only_in_{v1}"] = only_v1_file

        if comparison_data["only_in_version2"]:
            df = pd.DataFrame(comparison_data["only_in_version2"])
            only_v2_file = os.path.join(self.output_dir, f"{filename_prefix}_only_in_{v2}.csv")
            df.to_csv(only_v2_file, index=False, encoding="utf-8-sig")
            files[f"only_in_{v2}"] = only_v2_file

        return files
