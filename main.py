"""
FinSight - 用户模式入口
用户看到的界面：干净聊天 + 研报链接，无调试信息
"""

from __future__ import annotations

import os

import uvicorn

from src.app.api_fastapi import create_fastapi_app

app = create_fastapi_app(mode="user")

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")))
