"""config 单测：环境变量覆盖默认值、.env 加载不破坏默认行为。"""

from yk_agent.config import Settings


def test_defaults():
    s = Settings(_env_file=None, ark_api_key="")  # 屏蔽 .env，只测代码内默认值
    assert s.max_orchestration_steps == 15
    assert s.ark_base_url.startswith("https://ark.")
    assert s.model_chat.startswith("doubao")


def test_env_override(monkeypatch):
    monkeypatch.setenv("YK_MAX_ORCHESTRATION_STEPS", "5")
    monkeypatch.setenv("YK_ARK_API_KEY", "test-key")
    s = Settings(_env_file=None)  # 不读 .env 文件，只用环境变量
    assert s.max_orchestration_steps == 5
    assert s.ark_api_key == "test-key"


def test_global_env_var_does_not_leak(monkeypatch):
    """项目变量必须隔离于全局环境：不带 YK_ 前缀的同名变量不得生效。"""
    monkeypatch.setenv("ARK_API_KEY", "leaked-global-key")
    s = Settings(_env_file=None)
    assert s.ark_api_key != "leaked-global-key"
