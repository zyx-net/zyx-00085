# 小区泵房巡检异常分析工具

一个功能完整的本地泵房巡检数据异常分析工具，支持传感器读数核对、巡检班次管理、设备台账管理、异常检测、人工复核、规则版本管理和报告导出。

## 功能特性

### 核心功能
- **数据导入**: 支持 CSV 和 Excel 格式的传感器读数、巡检班次、设备台账导入
- **字段映射**: 可配置的字段映射，支持中文列名自动映射
- **必填列校验**: 导入时自动校验必填列是否存在
- **批次持久化**: 所有导入数据按批次管理，数据持久化到 SQLite 数据库
- **异常检测引擎**: 支持 7 种异常类型检测
- **人工复核**: 支持对异常进行复核标注（确认异常/误报）
- **回滚机制**: 支持回滚复核结果
- **规则版本管理**: 支持多版本检测规则，可切换、可对比
- **报告导出**: 支持 HTML 和 CSV 格式报告导出
- **原始数据保留**: 所有原始导入行完整保存，不丢失

### 异常检测类型
| 异常代码 | 异常名称 | 说明 |
|---------|---------|------|
| PRESSURE_SUDDEN_DROP | 水压突降 | 短时间内水压下降超过阈值 |
| LONG_TIME_OFFLINE | 长时间离线 | 设备超过设定时间无读数 |
| READING_BACKWARD | 读数倒退 | 流量读数出现倒退 |
| DUPLICATE_REPORT | 重复上报 | 同一设备短时间内多次上报 |
| UNREGISTERED_DEVICE | 未登记设备 | 读数中出现台账中不存在的设备 |
| SAME_TIME_DIFFERENT_READING | 同时刻不同读数 | 同一设备同一时间点出现不同读数 |
| PRESSURE_OUT_OF_RANGE | 水压超限 | 水压超出设备台账设定的上下限 |

### 可复现的错误场景
1. **缺少设备编号列**: `sensor_readings_missing_device_id.csv` - 导入时会校验失败
2. **错误时区**: `sensor_readings_wrong_timezone.csv` - 包含 UTC 和其他时区的时间
3. **同设备同时间不同读数**: 主数据文件中 PUMP-002 在 08:15:00 有两条不同水压读数
4. **引用不存在设备**: 主数据文件中 PUMP-999 未在设备台账中登记

## 项目结构

```
zyx-00085/
├── pump_inspection/          # 核心包
│   ├── __init__.py
│   ├── database.py          # 数据库连接
│   ├── models.py            # 数据模型
│   ├── field_mapper.py      # 字段映射
│   ├── validator.py         # 数据校验
│   ├── anomaly_detector.py  # 异常检测引擎
│   ├── batch_manager.py     # 批次管理
│   ├── rule_manager.py      # 规则版本管理
│   └── report_exporter.py   # 报告导出
├── config/                   # 配置文件
│   ├── field_mapping.json       # 字段映射配置
│   ├── validation_rules.json    # 校验规则
│   ├── detection_rules_v1.json  # 检测规则 v1
│   └── detection_rules_v2.json  # 检测规则 v2
├── sample_data/              # 样例数据
│   ├── equipment_ledger.csv              # 设备台账
│   ├── inspection_shifts.csv             # 巡检班次
│   ├── sensor_readings_normal.csv        # 正常数据
│   ├── sensor_readings_with_anomalies.csv # 含异常数据
│   ├── sensor_readings_missing_device_id.csv # 缺少设备编号列
│   └── sensor_readings_wrong_timezone.csv    # 错误时区
├── reports/                  # 报告输出目录
├── main.py                   # 命令行入口
├── requirements.txt          # 依赖
└── README.md                 # 本文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行完整演示流程

```bash
python main.py run-full-flow
```

此命令将自动执行以下步骤：
1. 初始化数据库
2. 导入设备台账
3. 设置规则版本为 v2
4. 创建分析批次
5. 导入传感器读数（含异常）
6. 导入巡检班次
7. 运行异常检测
8. 人工复核一条异常（标记为误报）
9. 回滚该复核结果
10. 复核第二条异常（确认真实异常）
11. 导出 HTML 和 CSV 报告
12. 测试错误场景（缺少设备编号列）
13. 测试错误场景（错误时区）
14. 显示复核历史
15. 显示所有批次汇总

### 3. 预期异常数量

使用样例数据 `sensor_readings_with_anomalies.csv` 时，预期检测到以下异常（使用 v2 规则）：

| 异常类型 | 数量 | 说明 |
|---------|------|------|
| 重复上报 | 2 | PUMP-001 在 08:00:00 和 08:00:30 两次上报 (120秒窗口) |
| 水压突降 | 2 | PUMP-001 在 08:15-08:20 从 0.46 降到 0.25 (降幅 0.21, 15分钟窗口) |
| 长时间离线 | 2 | PUMP-001 08:45-13:00 (4h15m), PUMP-003 16:30-21:00 (4h30m) |
| 同时刻不同读数 | 2 | PUMP-002 在 08:15:00 有 0.51 和 0.60 两条记录 |
| 读数倒退 | 1 | PUMP-002 流量从 155.5 降到 130.0 (下降 25.5m³/h) |
| 水压超限 | 2 | PUMP-004 达到 0.95 (上限 0.90), PUMP-006 降到 0.05 (下限 0.18) |
| 未登记设备 | 2 | PUMP-999 的两条记录 |
| **合计** | **13** | |

### 4. 分步命令

#### 初始化数据库
```bash
python main.py init-db
```

#### 导入设备台账
```bash
python main.py import-equipment
# 或指定文件
python main.py import-equipment --file sample_data/equipment_ledger.csv
```

#### 查看设备台账
```bash
python main.py list-equipment
```

#### 创建分析批次
```bash
python main.py create-batch --name "2026年6月数据分析"
# 指定规则版本
python main.py create-batch --name "测试批次" --rule-version v1
```

#### 导入传感器读数
```bash
python main.py import-readings --batch-id 1
# 跳过校验
python main.py import-readings --batch-id 1 --skip-validation
```

#### 导入巡检班次
```bash
python main.py import-shifts --batch-id 1
```

#### 运行异常检测
```bash
python main.py detect --batch-id 1
```
预期输出（使用 v2 规则）：共发现 **13 条** 异常
- 水压超限: 2 条
- 长时间离线: 2 条
- 读数倒退: 1 条
- 水压突降: 2 条
- 重复上报: 2 条
- 同时刻不同读数: 2 条
- 未登记设备: 2 条

#### 查看所有批次
```bash
python main.py list-batches
```

#### 查看批次异常
```bash
python main.py list-anomalies --batch-id 1
# 只看未复核的
python main.py list-anomalies --batch-id 1 --reviewed no
# 只看已复核的
python main.py list-anomalies --batch-id 1 --reviewed yes
```
预期输出：列出 13 条异常明细，包含异常 ID、类型、严重度、设备、时间、描述等信息

#### 复核异常
```bash
# 标记为误报
python main.py review --anomaly-id 1 --result false_positive --notes "传感器临时波动" --reviewer "张三"
# 确认真实异常
python main.py review --anomaly-id 2 --result confirmed --notes "现场核实，确有异常" --reviewer "李四"
```

#### 回滚复核结果
```bash
python main.py rollback --anomaly-id 1
```

#### 规则版本管理
```bash
# 列出所有规则版本
python main.py list-rules
# 切换使用的规则版本
python main.py use-rule --version v2
```

#### 导出报告
```bash
# 导出 HTML 报告
python main.py export-html --batch-id 1
# 导出时不包含原始数据
python main.py export-html --batch-id 1 --no-raw-data
# 指定输出文件名
python main.py export-html --batch-id 1 --output my_report.html

# 导出 CSV 报告（多个文件）
python main.py export-csv --batch-id 1
# 导出所有批次汇总
python main.py export-summary
```

## 数据持久化验证

所有数据都保存在 SQLite 数据库 `pump_inspection.db` 中，重启程序后以下信息保持一致：

- ✅ 批次列表和状态
- ✅ 复核历史记录
- ✅ 回滚操作结果
- ✅ 规则版本配置
- ✅ 导出报告汇总
- ✅ 所有原始导入数据

验证方法：
1. 运行 `python main.py run-full-flow` 完成演示
2. 记录显示的批次信息和异常数量
3. 重新运行 `python main.py list-batches`
4. 确认所有信息与之前一致

## 配置说明

### 字段映射配置 (`config/field_mapping.json`)
定义中文列名到英文字段名的映射关系，可根据实际数据文件修改。

### 校验规则配置 (`config/validation_rules.json`)
定义各类型数据的必填列、唯一列和数值范围。

### 检测规则配置 (`config/detection_rules_v*.json`)
定义异常检测的阈值参数。v1 和 v2 版本的主要差异：

| 规则 | v1 | v2 |
|-----|-----|-----|
| 水压突降阈值 | 0.15 MPa / 30分钟 | 0.10 MPa / 15分钟 |
| 重复上报时间窗口 | 60 秒 | 120 秒 |

## 异常场景测试命令

### 测试缺少设备编号列
```bash
python main.py create-batch --name "测试_缺少设备编号"
python main.py import-readings --batch-id 2 --file sample_data/sensor_readings_missing_device_id.csv
```
预期输出：导入失败，提示 `缺少必填列: device_id`

### 测试错误时区
```bash
python main.py create-batch --name "测试_错误时区"
python main.py import-readings --batch-id 3 --file sample_data/sensor_readings_wrong_timezone.csv --skip-validation
python main.py detect --batch-id 3
```
预期输出：识别到时区问题，异常检测正常运行

## 技术栈

- **Python 3.8+**
- **SQLAlchemy 2.0+** - ORM 和数据库操作
- **Pandas** - 数据处理
- **Jinja2** - HTML 报告模板
- **SQLite** - 本地数据库
- **openpyxl** - Excel 文件支持

## 代码参考

- 数据模型: [models.py](file:///d:/workSpace/AI__SPACE/zyx-00085/pump_inspection/models.py)
- 异常检测引擎: [anomaly_detector.py](file:///d:/workSpace/AI__SPACE/zyx-00085/pump_inspection/anomaly_detector.py#L15-L41)
- 批次管理: [batch_manager.py](file:///d:/workSpace/AI__SPACE/zyx-00085/pump_inspection/batch_manager.py)
- 报告导出: [report_exporter.py](file:///d:/workSpace/AI__SPACE/zyx-00085/pump_inspection/report_exporter.py)
- 主流程入口: [main.py](file:///d:/workSpace/AI__SPACE/zyx-00085/main.py)
