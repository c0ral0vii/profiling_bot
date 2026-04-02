import asyncio
import re
from collections import deque
from dataclasses import dataclass

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
from ocr.main import check_img

dp = Dispatcher()


@dataclass(slots=True)
class UserTask:
    message: Message
    user_id: int
    url: str
    coord_status: bool


user_queues: dict[int, deque[UserTask]] = {}
user_workers: dict[int, asyncio.Task] = {}
user_queue_lock = asyncio.Lock()


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
        result = await stop_user_tasks(message.from_user.id)
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
    """Ставит ссылку пользователя в очередь на обработку"""
    data = await state.get_data()
    if not data.get("coord_status"):
        await state.update_data(coord_status=False)
        data = await state.get_data()

    queued_before = await enqueue_user_task(
        message=message,
        coord_status=data.get("coord_status", False),
    )

    if queued_before > 0:
        await message.reply(
            f"Ссылка поставлена в очередь. Перед вами задач: {queued_before}."
        )


async def enqueue_user_task(message: Message, coord_status: bool) -> int:
    """Добавляет задачу пользователя в очередь и запускает воркер при необходимости."""
    user_id = message.from_user.id
    task = UserTask(
        message=message,
        user_id=user_id,
        url=message.text,
        coord_status=coord_status,
    )

    async with user_queue_lock:
        queue = user_queues.setdefault(user_id, deque())
        worker = user_workers.get(user_id)
        worker_running = worker is not None and not worker.done()

        queue.append(task)
        queued_before = len(queue) if worker_running else len(queue) - 1

        if not worker_running:
            user_workers[user_id] = asyncio.create_task(process_user_queue(user_id))

    return queued_before


async def process_user_queue(user_id: int):
    """Последовательно обрабатывает ссылки одного пользователя."""
    try:
        while True:
            async with user_queue_lock:
                queue = user_queues.get(user_id)
                if not queue:
                    user_queues.pop(user_id, None)
                    return

                task = queue.popleft()

            await process_user_task(task)
    except asyncio.CancelledError:
        async with user_queue_lock:
            user_queues.pop(user_id, None)
        raise
    finally:
        async with user_queue_lock:
            worker = user_workers.get(user_id)
            if worker is asyncio.current_task():
                user_workers.pop(user_id, None)


async def process_user_task(task: UserTask):
    """Проверка и обработка одной ссылки пользователя."""
    msg = await task.message.reply("Получаем изображения с файлообменника...")

    try:
        img_urls = await get_imgs(url=task.url, user=task.user_id)
        await msg.edit_text(" ✅Изображения получены, получаем координаты...")

        result = await check_img(
            img_urls=img_urls, coord_status=task.coord_status
        )
        await msg.edit_text(" ✅Координаты получены, создаём карту...")

        await create_html(coords=result[0], user=task.user_id)
        await safe_delete_message(msg)

        await task.message.reply_document(
            FSInputFile(path=f"map/generate_map/{str(task.user_id)}/leaflet.html"),
            caption=f"Готово ✅, {result[-1]}",
        )

        processed_coords = result[0]
        processed_urls = set(processed_coords.keys())
        unprocessed_urls = [url for url in img_urls if url not in processed_urls]

        if unprocessed_urls:
            links_message = "📸 Необработанные изображения:\n"
            for i, url in enumerate(unprocessed_urls, 1):
                links_message += f"{i}. {url}\n"

            await send_long_message(links_message, task.message)

    except asyncio.CancelledError:
        await safe_delete_message(msg)
        raise
    except Exception as e:
        await safe_delete_message(msg)
        await task.message.answer(
            f"Произошла ошибка при обработке, повторите попытку ({e})"
        )


async def stop_user_tasks(user_id: int) -> str:
    """Останавливает текущую обработку и очищает очередь пользователя."""
    async with user_queue_lock:
        queue = user_queues.pop(user_id, deque())
        worker = user_workers.pop(user_id, None)

    queued_count = len(queue)
    is_running = worker is not None and not worker.done()

    if is_running:
        worker.cancel()

    if not is_running and queued_count == 0:
        return "Никаких задач сейчас нет"

    stopped_total = queued_count + int(is_running)
    return f"Остановлено задач: {stopped_total}"


async def safe_delete_message(message: Message):
    """Безопасное удаление служебного сообщения."""
    try:
        await message.delete()
    except Exception:
        pass


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
