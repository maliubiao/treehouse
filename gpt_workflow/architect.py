import re
from typing import Dict, List


class ArchitectMode:
    """
    架构师模式响应解析器

    输入格式规范:
    [task describe start]
    {{多行任务描述}}
    [task describe end]

    [team member {{成员ID}} job start]
    {{多行工作内容}}
    [team member {{成员ID}} job end]
    """

    TASK_PATTERN = re.compile(r"\[task describe start\](.*?)\[task describe end\]", re.DOTALL)
    JOB_BLOCK_PATTERN = re.compile(
        r"\[team member(?P<member_id>\w+) job start\](.*?)\[team member\1 job end\]", re.DOTALL
    )

    @staticmethod
    def parse_response(response: str) -> dict:
        """
        解析架构师模式生成的响应文本

        参数:
            response: 包含任务描述和工作分配的格式化文本

        返回:
            dict: {
                "task": "清理后的任务描述文本",
                "jobs": [
                    {"member": "成员ID", "content": "清理后的工作内容"},
                    ...
                ]
            }

        异常:
            ValueError: 当关键标签缺失或格式不符合规范时
            RuntimeError: 当工作块存在不匹配的标签时
        """
        parsed_data = {"task": "", "jobs": []}
        parsed_data.update(ArchitectMode._parse_task_section(response))
        parsed_data["jobs"] = ArchitectMode._parse_job_sections(response)
        ArchitectMode._validate_parsed_data(parsed_data)
        return parsed_data

    @staticmethod
    def _parse_task_section(text: str) -> dict:
        """解析任务描述部分"""
        task_match = ArchitectMode.TASK_PATTERN.search(text)
        if not task_match:
            raise ValueError("缺少必要的任务描述标签对")

        raw_task = task_match.group(1).strip()
        if not raw_task:
            raise ValueError("任务描述内容不能为空")

        return {"task": raw_task}

    @staticmethod
    def _parse_job_sections(text: str) -> list:
        """解析所有工作块并验证一致性"""
        jobs = []
        seen_members = set()

        for match in ArchitectMode.JOB_BLOCK_PATTERN.finditer(text):
            member_id = match.group("member_id")
            if member_id in seen_members:
                raise RuntimeError(f"检测到重复的成员ID: {member_id}")

            content = match.group(2).strip()
            if not content:
                raise ValueError(f"成员{member_id}的工作内容为空")

            jobs.append({"member": member_id, "content": content})
            seen_members.add(member_id)

        if not jobs:
            raise ValueError("未找到有效的工作分配块")

        return jobs

    @staticmethod
    def _validate_parsed_data(data: dict):
        """验证解析后的数据结构完整性"""
        if not isinstance(data.get("task"), str) or len(data["task"]) < 10:
            raise ValueError("解析后的任务描述不完整或过短")

        if len(data["jobs"]) == 0:
            raise ValueError("未解析到有效的工作分配")

        for idx, job in enumerate(data["jobs"]):
            if len(job["content"]) < 10:
                raise ValueError(f"成员{job['member']}的工作内容过短")
