from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from .middlewares import ValidAccounts
from config.config import BOT_API_TOKEN
from map.main import check_filesharing

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    print(message.from_user.id)
    await message.reply('Отправь мне ссылку на файлообменник')


@dp.message()
async def get_filesharing(message: Message):
    '''Проверка на файлообменник'''

    user_id = message.from_user
    await message.reply(await check_filesharing(f'Идёт обработка, пожалуйста подождите...'))
    await check_filesharing(text=message.text, user=user_id)
    await message.reply(await check_filesharing(text=message.text, user=user_id))


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN, parse_mode=ParseMode.HTML)

    await dp.start_polling(bot)


