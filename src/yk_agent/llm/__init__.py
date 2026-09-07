"""模型接入抽象层：LLMProvider 统一接口（chat/embed），默认火山方舟（OpenAI 协议兼容）。

硬规则：业务代码禁止直接 import 任何厂商 SDK，一律经本包工厂获取 provider。
接口定义见 docs/02-architecture.md §模型接入层。
"""
