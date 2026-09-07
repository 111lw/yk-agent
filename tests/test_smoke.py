"""冒烟测试：包可导入、版本可读。实现各模块后替换为真实单测（见 CLAUDE.md 编码规范）。"""

import yk_agent


def test_package_importable():
    assert yk_agent.__version__ == "0.1.0"
