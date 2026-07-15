#!/usr/bin/env python3
"""Entry point — run with: python backend/run.py"""
import uvicorn
from backend.config.settings import get_settings


if __name__ == "__main__":
    rs = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=rs.host,
        port=rs.port,
        log_level=rs.log_level.lower(),
        reload=False,
    )
