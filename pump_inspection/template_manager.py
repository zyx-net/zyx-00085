import json
import os
import tempfile
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from .models import InspectionTemplate, RuleVersion


class TemplateError(Exception):
    """模板操作自定义异常"""
    pass


class TemplateManager:
    def __init__(self, db_session: Session):
        self.db = db_session

    def _validate_template_data(
        self,
        name: str,
        rule_version: str,
        threshold_overrides: Optional[Dict] = None,
        remark_fields: Optional[List[Dict]] = None,
        report_preferences: Optional[Dict] = None,
        exclude_id: Optional[int] = None
    ) -> Tuple[bool, List[str]]:
        """验证模板数据的合法性"""
        errors = []

        if not name or not name.strip():
            errors.append("模板名称不能为空")
        elif len(name.strip()) > 200:
            errors.append("模板名称长度不能超过200字符")
        else:
            query = self.db.query(InspectionTemplate).filter(
                InspectionTemplate.name == name.strip()
            )
            if exclude_id:
                query = query.filter(InspectionTemplate.id != exclude_id)
            existing = query.first()
            if existing:
                errors.append(f"模板名称 '{name.strip()}' 已存在，请使用其他名称")

        if not rule_version or not rule_version.strip():
            errors.append("规则版本不能为空")
        else:
            rv = self.db.query(RuleVersion).filter(
                RuleVersion.version == rule_version.strip()
            ).first()
            if not rv:
                errors.append(f"规则版本 '{rule_version.strip()}' 不存在")

        if threshold_overrides is not None:
            if not isinstance(threshold_overrides, dict):
                errors.append("阈值覆盖必须是字典格式")
            else:
                for rule_name, overrides in threshold_overrides.items():
                    if not isinstance(overrides, dict):
                        errors.append(f"规则 '{rule_name}' 的阈值配置必须是字典")
                        continue
                    for key, value in overrides.items():
                        if key in ["threshold", "threshold_hours", "time_window_minutes",
                                   "time_window_seconds"]:
                            if not isinstance(value, (int, float)):
                                errors.append(f"规则 '{rule_name}' 的 '{key}' 必须是数字")
                            elif value < 0:
                                errors.append(f"规则 '{rule_name}' 的 '{key}' 不能为负数")

        if remark_fields is not None:
            if not isinstance(remark_fields, list):
                errors.append("备注字段配置必须是列表格式")
            else:
                for i, field in enumerate(remark_fields):
                    if not isinstance(field, dict):
                        errors.append(f"第 {i+1} 个备注字段必须是字典格式")
                        continue
                    if "content" not in field:
                        errors.append(f"第 {i+1} 个备注字段缺少 'content' 字段")
                    elif not field["content"] or not str(field["content"]).strip():
                        errors.append(f"第 {i+1} 个备注字段的 'content' 不能为空")

        if report_preferences is not None:
            if not isinstance(report_preferences, dict):
                errors.append("报告输出偏好必须是字典格式")
            else:
                valid_keys = ["include_raw_data", "export_format", "include_remarks",
                              "include_review_history", "filename_prefix"]
                for key in report_preferences:
                    if key not in valid_keys:
                        errors.append(f"报告偏好 '{key}' 不是有效配置项，有效项: {valid_keys}")

        return len(errors) == 0, errors

    def create_template(
        self,
        name: str,
        rule_version: str,
        description: str = "",
        threshold_overrides: Optional[Dict] = None,
        remark_fields: Optional[List[Dict]] = None,
        report_preferences: Optional[Dict] = None,
        created_by: str = "system"
    ) -> InspectionTemplate:
        """创建新模板"""
        name = name.strip() if name else ""
        rule_version = rule_version.strip() if rule_version else ""

        is_valid, errors = self._validate_template_data(
            name, rule_version, threshold_overrides, remark_fields, report_preferences
        )
        if not is_valid:
            raise TemplateError("; ".join(errors))

        template = InspectionTemplate(
            name=name,
            description=description or "",
            rule_version=rule_version,
            threshold_overrides=json.dumps(threshold_overrides, ensure_ascii=False) if threshold_overrides else None,
            remark_fields=json.dumps(remark_fields, ensure_ascii=False) if remark_fields else None,
            report_preferences=json.dumps(report_preferences, ensure_ascii=False) if report_preferences else None,
            created_by=created_by
        )
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def get_template(self, template_id: Optional[int] = None, name: Optional[str] = None) -> Optional[InspectionTemplate]:
        """根据ID或名称获取模板"""
        if template_id:
            return self.db.query(InspectionTemplate).filter(
                InspectionTemplate.id == template_id
            ).first()
        if name:
            return self.db.query(InspectionTemplate).filter(
                InspectionTemplate.name == name.strip()
            ).first()
        return None

    def get_all_templates(self) -> List[InspectionTemplate]:
        """获取所有模板"""
        return self.db.query(InspectionTemplate).order_by(
            InspectionTemplate.updated_at.desc()
        ).all()

    def update_template(
        self,
        template_id: int,
        name: Optional[str] = None,
        rule_version: Optional[str] = None,
        description: Optional[str] = None,
        threshold_overrides: Optional[Dict] = None,
        remark_fields: Optional[List[Dict]] = None,
        report_preferences: Optional[Dict] = None
    ) -> InspectionTemplate:
        """更新模板"""
        template = self.get_template(template_id=template_id)
        if not template:
            raise TemplateError(f"模板 ID={template_id} 不存在")

        new_name = name.strip() if name else template.name
        new_rule_version = rule_version.strip() if rule_version else template.rule_version

        current_threshold = json.loads(template.threshold_overrides) if template.threshold_overrides else None
        current_remarks = json.loads(template.remark_fields) if template.remark_fields else None
        current_prefs = json.loads(template.report_preferences) if template.report_preferences else None

        is_valid, errors = self._validate_template_data(
            new_name,
            new_rule_version,
            threshold_overrides if threshold_overrides is not None else current_threshold,
            remark_fields if remark_fields is not None else current_remarks,
            report_preferences if report_preferences is not None else current_prefs,
            exclude_id=template_id
        )
        if not is_valid:
            raise TemplateError("; ".join(errors))

        if name is not None:
            template.name = new_name
        if rule_version is not None:
            template.rule_version = new_rule_version
        if description is not None:
            template.description = description
        if threshold_overrides is not None:
            template.threshold_overrides = json.dumps(threshold_overrides, ensure_ascii=False)
        if remark_fields is not None:
            template.remark_fields = json.dumps(remark_fields, ensure_ascii=False)
        if report_preferences is not None:
            template.report_preferences = json.dumps(report_preferences, ensure_ascii=False)

        template.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(template)
        return template

    def rename_template(self, template_id: int, new_name: str) -> InspectionTemplate:
        """重命名模板"""
        return self.update_template(template_id, name=new_name)

    def delete_template(self, template_id: Optional[int] = None, name: Optional[str] = None) -> bool:
        """删除模板"""
        template = self.get_template(template_id=template_id, name=name)
        if not template:
            raise TemplateError("模板不存在")
        self.db.delete(template)
        self.db.commit()
        return True

    def apply_template(
        self,
        template_id: Optional[int] = None,
        name: Optional[str] = None
    ) -> Dict:
        """应用模板，返回可用于创建批次和报告的配置"""
        template = self.get_template(template_id=template_id, name=name)
        if not template:
            raise TemplateError("模板不存在")

        config = {
            "rule_version": template.rule_version,
            "threshold_overrides": json.loads(template.threshold_overrides) if template.threshold_overrides else {},
            "remark_fields": json.loads(template.remark_fields) if template.remark_fields else [],
            "report_preferences": json.loads(template.report_preferences) if template.report_preferences else {},
            "template_name": template.name,
            "template_id": template.id,
            "description": template.description
        }
        return config

    def template_to_dict(self, template: InspectionTemplate) -> Dict:
        """将模板转换为字典（用于导出）"""
        return {
            "name": template.name,
            "description": template.description,
            "rule_version": template.rule_version,
            "threshold_overrides": json.loads(template.threshold_overrides) if template.threshold_overrides else {},
            "remark_fields": json.loads(template.remark_fields) if template.remark_fields else [],
            "report_preferences": json.loads(template.report_preferences) if template.report_preferences else {},
            "created_by": template.created_by,
            "exported_at": datetime.now().isoformat()
        }

    def export_template_to_json(
        self,
        template_id: Optional[int] = None,
        name: Optional[str] = None,
        output_file: Optional[str] = None
    ) -> Tuple[Dict, Optional[str]]:
        """导出模板为JSON"""
        template = self.get_template(template_id=template_id, name=name)
        if not template:
            raise TemplateError("模板不存在")

        data = self.template_to_dict(template)

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        return data, output_file

    def import_template_from_json(
        self,
        input_file: str,
        on_conflict: str = "ask"
    ) -> Tuple[InspectionTemplate, str]:
        """从JSON导入模板

        Args:
            input_file: JSON文件路径
            on_conflict: 冲突处理方式 - "error"（报错）, "rename"（自动重命名）, "skip"（跳过）

        Returns:
            (导入的模板, 处理状态说明)
        """
        if not os.path.exists(input_file):
            raise TemplateError(f"文件不存在: {input_file}")

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise TemplateError(f"JSON格式错误: {str(e)}")
        except Exception as e:
            raise TemplateError(f"读取文件失败: {str(e)}")

        required_fields = ["name", "rule_version"]
        for field in required_fields:
            if field not in data or not data[field]:
                raise TemplateError(f"导入数据缺少必填字段: '{field}'")

        name = data["name"].strip()
        existing = self.get_template(name=name)

        if existing:
            if on_conflict == "error":
                raise TemplateError(
                    f"模板名称 '{name}' 已存在。如需覆盖请使用 --overwrite，"
                    f"如需自动重命名请使用 --auto-rename，如需跳过请使用 --skip-existing"
                )
            elif on_conflict == "skip":
                return existing, f"已跳过: 模板 '{name}' 已存在"
            elif on_conflict == "rename":
                base_name = name
                counter = 1
                while True:
                    new_name = f"{base_name}_导入{counter}"
                    if not self.get_template(name=new_name):
                        name = new_name
                        break
                    counter += 1
                status = f"已自动重命名: '{data['name']}' -> '{name}'"
            else:
                raise TemplateError(f"无效的冲突处理方式: {on_conflict}")
        else:
            status = "成功导入"

        try:
            template = self.create_template(
                name=name,
                rule_version=data["rule_version"],
                description=data.get("description", ""),
                threshold_overrides=data.get("threshold_overrides"),
                remark_fields=data.get("remark_fields"),
                report_preferences=data.get("report_preferences"),
                created_by=data.get("created_by", "import")
            )
            return template, status
        except TemplateError as e:
            raise TemplateError(f"导入数据验证失败: {str(e)}")

    def export_all_templates(self, output_file: str) -> str:
        """导出所有模板为一个JSON文件"""
        templates = self.get_all_templates()
        data = {
            "exported_at": datetime.now().isoformat(),
            "template_count": len(templates),
            "templates": [self.template_to_dict(t) for t in templates]
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return output_file

    def import_templates_from_bulk_json(
        self,
        input_file: str,
        on_conflict: str = "ask"
    ) -> List[Tuple[Optional[InspectionTemplate], str]]:
        """从批量JSON文件导入多个模板"""
        if not os.path.exists(input_file):
            raise TemplateError(f"文件不存在: {input_file}")

        try:
            with open(input_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise TemplateError(f"JSON格式错误: {str(e)}")

        if "templates" not in data or not isinstance(data["templates"], list):
            raise TemplateError("批量导入文件格式错误，缺少 'templates' 列表")

        results = []
        original_on_conflict = on_conflict

        for template_data in data["templates"]:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as tmp:
                    json.dump(template_data, tmp, ensure_ascii=False, indent=2)
                    tmp_path = tmp.name

                try:
                    template, status = self.import_template_from_json(
                        tmp_path, on_conflict=original_on_conflict
                    )
                    results.append((template, status))
                finally:
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass
            except TemplateError as e:
                results.append((None, f"失败: {template_data.get('name', '未知')} - {str(e)}"))

        return results
