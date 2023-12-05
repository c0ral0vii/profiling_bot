import asyncio

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart

from ..config.config import BOT_API_TOKEN, filesharings


bot = Bot(BOT_API_TOKEN)

dp = Dispatcher(bot)


@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    await message.reply('Отправь мне ссылку на файлообменник')


@dp.message(F.text in filesharings)
async def check_link(message: Message):
    await message.reply(message.text)


async def run():
    '''Запуск бота'''

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)