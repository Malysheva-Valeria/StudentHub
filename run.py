"""Run StudentHub: python run.py"""
import sys

import uvicorn

from app.config import ConfigError, load_settings
from app.db import init_db
from app.migrations import MigrationError

if __name__ == "__main__":
    try:
        s = load_settings()
        # Migrate before starting so errors show as a message, not a traceback
        init_db(s.db_path)
    except ConfigError as e:
        sys.exit(f"Помилка конфігурації: {e}")
    except MigrationError as e:
        sys.exit(f"Помилка бази даних: {e}")
    print(f"StudentHub: http://{s.host}:{s.port}" + ("" if s.production else f"  (API-документація: http://{s.host}:{s.port}/api/docs)"))
    uvicorn.run(
        "app.main:create_app", factory=True, host=s.host, port=s.port, reload=False,
        # Trust X-Forwarded-For only from configured proxies, else client IPs (and rate limits) are spoofable
        proxy_headers=s.forwarded_allow_ips is not None,
        forwarded_allow_ips=s.forwarded_allow_ips,
    )
