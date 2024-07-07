import asyncio
import re

from aiogram import F, Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart

from config.config import BOT_API_TOKEN, filesharings
from map.files import create_new_user
from ocr.main import check_img, stop
from map.parsing import get_imgs
from map.main import create_html


dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    '''Стартовое сообщение'''

    user = create_new_user(user=message.from_user.id)
    stop_answer = await stop()
    await message.reply(f'Отправь мне ссылку на файлообменник, {stop_answer}')


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
    user_id = message.from_user.id
    msg = await message.reply('Получаем изображения с файлообменника...')

    img_urls = await get_imgs(url=message.text, user=user_id)
    await msg.edit_text(' ✅Изображения получены, получаем координаты...')

    result = await check_img(img_urls=img_urls)
    await msg.edit_text(' ✅Координаты получены, создаём карту...')

    await create_html(coords=result[0], user=user_id)
    await msg.delete()

    await message.reply_document(FSInputFile(path=f'map/generate_map/{str(user_id)}/leaflet.html'),
                                 caption=f"Готово ✅, {result[-1]}")


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)


