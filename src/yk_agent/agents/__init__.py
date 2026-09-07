"""子智能体：Agent Registry 与各子智能体实现（poi / route / budget）。

规则：必须经 Registry 注册（含 description/input_schema/output_schema/side_effect），
禁止业务代码硬编码调用。设计文档：docs/03-agent-orchestration.md。
"""
