"""
FinSight - 开发者模式入口（本地调试用）
显示全部内容：质量门禁、LLM 复核、工具调用、Agent 时间线、12 个调试标签页
"""

from __future__ import annotations

import os

import uvicorn

from src.app.api_fastapi import create_fastapi_app

app = create_fastapi_app(mode="developer")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    print("=" * 60)
    print("  FinSight 开发者模式")
    print("  本地调试：http://127.0.0.1:{}/?mode=developer".format(port))
    print("  完整调试面板可用")
    print("=" * 60)
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=port)
