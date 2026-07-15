from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from config.settings import settings


def main() -> None:
    load_dotenv()
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        factory=False,
        loop="uvloop",
    )


if __name__ == "__main__":
    main()
