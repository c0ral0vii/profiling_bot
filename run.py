import asyncio
import logging
import sys
import requests

from bot.main import run_bot
from map.main import check_imgs

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(run_bot())