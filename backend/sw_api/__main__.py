"""Run with python -m sw_api or sw-api."""
import uvicorn
from .config import Settings


def main() -> None:
    """One process owns the memory ward and sessions; plain asyncio/h11 on s390x."""
    settings = Settings.from_env()
    uvicorn.run("sw_api.app:create_app", factory=True, host=settings.api_host, port=settings.api_port,
                loop="asyncio", http="h11", ws="websockets-sansio", workers=1)


if __name__ == "__main__":
    main()
