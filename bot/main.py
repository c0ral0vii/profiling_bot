import re

from aiogram import Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from .middlewares import ValidAccounts
from config.config import BOT_API_TOKEN, filesharings
from map.files import create_new_user
from map.main import check_filesharing

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    print(message.from_user.id)
    print(create_new_user(user=message.from_user.id))
    await message.reply('Отправь мне ссылку на файлообменник')


@dp.message()
async def get_filesharing(message: Message):
    '''Проверка на файлообменник'''

    user_id = message.from_user.id
    regular = r'\b(?:{})\b'.format('|'.join(filesharings))
    result = re.search(regular, message.text)

    if result:
        await message.reply(f'Идёт обработка, подождите....')
        await check_filesharing(text=message.text, user=user_id)
        await message.reply_document(FSInputFile(path=f'map/generate_map/{user_id}/leaflet.html'), caption="Готово")
    else:
        await message.reply(f'В сообщени нет ссылки поддерживаемой нашим ботом')


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN, parse_mode=ParseMode.HTML)

    await dp.start_polling(bot)


