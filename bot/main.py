import asyncio
import re

from aiogram import F, Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext

from bot.states.fsm import AuthUser, Auth
from bot.func.auth import check_password, check_auth
from config.config import BOT_API_TOKEN, filesharings
from map.files import create_new_user
from ocr.main import check_img, stop
from map.parsing import get_imgs
from map.main import create_html


dp = Dispatcher()


@dp.message(CommandStart(), StateFilter(None))
async def start(message: Message, state: FSMContext):
    '''Стартовое сообщение'''

    user = create_new_user(user=message.from_user.id)
    if not await check_auth(user=message.from_user.id):
        await message.answer('Введите пароль:')
        await state.set_state(AuthUser.password)
    else:
        await message.answer('Ты авторизован, можешь пользоваться ботом..')


@dp.message(F.text, AuthUser.password)
async def login(message: Message, state: FSMContext):
    '''
    Вход
    '''

    if check_password(user=message.from_user.id, password=message.text):
        await state.clear()

        await message.answer(f'Вы ввели правильный пароль, можете пользоваться ботом..')
        await state.set_state(Auth.auth)
    else:
        await state.set_state(AuthUser.password)
        await message.answer('Вы ввели неправильный пароль!')


@dp.message(Command('help'), Auth.auth)
async def help(message: Message, state: FSMContext):
    '''Помощь'''

    await message.reply(f'')


@dp.message(Command('stop'), Auth.auth)
async def stop_func(message: Message, state: FSMContext):
    '''Стоп функция'''

    try:
        result = await stop()
        await message.answer(result)
    except Exception as e:
        await message.answer(f'Ошибка - {e}')


@dp.message(Auth.auth)
async def get_filesharing(message: Message, state: FSMContext):
    '''Проверка на файлообменник'''

    user_id = message.from_user.id
    regular = r'\b(?:{})\b'.format('|'.join(filesharings))
    result = re.search(regular, message.text)

    if result:
        await check_function(message=message)
    else:
        await message.reply(f'В сообщени нет ссылки поддерживаемой нашим ботом')


async def check_function(message: Message):
    try:
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
    except Exception as e:
        await msg.delete()
        await message.answer(f'Произошла ошибка при обработке, повторите попытку({e})')


async def run_bot():
    '''Запуск бота'''

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)


