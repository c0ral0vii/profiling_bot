import asyncio
import re

from aiogram import F, Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from config.config import BOT_API_TOKEN, filesharings
from map.files import create_new_user
from ocr.main import check_img
from map.parsing import get_imgs
from map.main import create_html
from map.main import check_filesharing

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    user = create_new_user(user=message.from_user.id)
    await message.reply('Отправь мне ссылку на файлообменник')


@dp.message()
async def get_filesharing(message: Message):
    '''Проверка на файлообменник'''

    user_id = message.from_user.id
    regular = r'\b(?:{})\b'.format('|'.join(filesharings))
    result = re.search(regular, message.text)

    if result:
        await check_function(message=message)
    else:
        await message.reply(f'В сообщени нет ссылки поддерживаемой нашим ботом')

async def check_function(message: Message):
    '''Проверка и отправка состояний'''

    user_id = message.from_user.id
    chat_id = message.chat.id
    await message.reply('Получаем изображения с файлообменника...')
    img_urls = await get_imgs(url=message.text, user=user_id)
    await message.reply(' ✅Изображения получены, получаем координаты...')
    result = await check_img(img_urls=img_urls)
    await message.reply(' ✅Координаты получены, создаём карту...')
    await create_html(coords=result[0], user=user_id)
    await message.reply_document(FSInputFile(path=f'map/generate_map/{str(user_id)}/leaflet.html'), caption=f"Готово ✅, {result[-1]}")

@dp.message(F.text == '/stop')
async def restart_bot(message: Message):
    '''Restart bot'''

    await message.answer('Проверка карты остановлена')


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)


