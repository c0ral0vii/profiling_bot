import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from bot.func.auth import check_password
from bot.states.fsm import Auth, AuthUser
from config.config import BOT_API_TOKEN, filesharings
from kb.main_menu import main_menu_keyboard
from map.files import create_new_user
from map.main import create_html
from map.parsing import get_imgs
from ocr.main import check_img, stop

dp = Dispatcher()


@dp.message(CommandStart(), StateFilter(None))
async def start(message: Message, state: FSMContext):
    """Стартовое сообщение"""

    await message.answer("Введите пароль:")
    await state.set_state(AuthUser.password)


@dp.message(F.text, AuthUser.password)
async def login(message: Message, state: FSMContext):
    """
    Вход
    """

    if await check_password(user=message.from_user.id, password=message.text):
        await state.clear()
        create_new_user(message.from_user.id)
        data = await state.get_data()
        if not data.get("coord_status"):
            await state.update_data(coord_status=False)
            data = await state.get_data()

        await message.answer(
            "Вы ввели правильный пароль, можете пользоваться ботом..",
            reply_markup=await main_menu_keyboard(data.get("coord_status")),
        )
        await state.set_state(Auth.auth)
    else:
        await state.set_state(AuthUser.password)
        await message.answer("Вы ввели неправильный пароль!")


@dp.message(Command("help"), Auth.auth)
async def help(message: Message, state: FSMContext):
    """Помощь"""

    await message.reply(
        "Авторизуйте, далее вы можете пользоваться ботом. Далее отправьте ссылку."
    )


@dp.message(Command("stop"), Auth.auth)
async def stop_func(message: Message, state: FSMContext):
    """Стоп функция"""

    try:
        result = await stop()
        await message.answer(result)
    except Exception as e:
        await message.answer(f"Ошибка - {e}")


@dp.message(F.text == "Включить/выключить проверку Тайланда", Auth.auth)
async def change_coord_status(message: Message, state: FSMContext):
    """Изменение координат"""

    data = await state.get_data()
    status = data.get("coord_status", False)
    new_status = not status

    await state.update_data(coord_status=new_status)
    status = (await state.get_data()).get("coord_status", False)

    await message.answer(
        "Координаты с одной цифрой: " + ("✅" if status else "❌"),
        reply_markup=await main_menu_keyboard(status),
    )


@dp.message(Auth.auth)
async def get_filesharing(message: Message, state: FSMContext):
    """Проверка на файлообменник"""

    regular = r"\b(?:{})\b".format("|".join(filesharings))
    result = re.search(regular, message.text)

    if result:
        await check_function(message=message, state=state)
    else:
        await message.reply("В сообщени нет ссылки поддерживаемой нашим ботом")


async def check_function(message: Message, state: FSMContext):
    """Проверка и обработка изображений"""
    try:
        data = await state.get_data()
        if not data.get("coord_status"):
            await state.update_data(coord_status=False)
            data = await state.get_data()

        user_id = message.from_user.id
        msg = await message.reply("Получаем изображения с файлообменника...")

        img_urls = await get_imgs(url=message.text, user=user_id)
        await msg.edit_text(" ✅Изображения получены, получаем координаты...")

        result = await check_img(
            img_urls=img_urls, coord_status=data.get("coord_status")
        )
        await msg.edit_text(" ✅Координаты получены, создаём карту...")

        await create_html(coords=result[0], user=user_id)
        await msg.delete()

        # Отправляем карту
        await message.reply_document(
            FSInputFile(path=f"map/generate_map/{str(user_id)}/leaflet.html"),
            caption=f"Готово ✅, {result[-1]}",
        )

        # Отправляем необработанные изображения ссылками
        processed_coords = result[0]
        processed_urls = set(processed_coords.keys())
        unprocessed_urls = [url for url in img_urls if url not in processed_urls]

        if unprocessed_urls:
            # Формируем сообщение со ссылками на необработанные изображения
            links_message = "📸 Необработанные изображения:\n"
            for i, url in enumerate(unprocessed_urls, 1):
                links_message += f"{i}. {url}\n"

            # Разбиваем на сообщения по 4000 символов
            await send_long_message(links_message, message)

    except Exception as e:
        await msg.delete()
        await message.answer(f"Произошла ошибка при обработке, повторите попытку ({e})")


async def send_long_message(text: str, message: Message, max_length: int = 4000):
    """Отправка длинного сообщения с разбивкой на части"""
    parts = []

    # Разбиваем текст на части по max_length символов
    while len(text) > max_length:
        # Ищем последнюю новую строку в пределах max_length
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        parts.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    if text:
        parts.append(text)

    # Отправляем каждую часть
    for part in parts:
        if part.strip():
            await message.answer(part)


async def run_bot():
    """Запуск бота"""

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)
