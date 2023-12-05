import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from config import BOT_API_TOKEN, filesharings


dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    await message.reply('Отправь мне ссылку на файлообменник')


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN, parse_mode=ParseMode.HTML)

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(run_bot())