import asyncio
import base64
import logging
import re
import zipfile
from collections import deque
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message
from aiohttp import web
from PIL import Image

from bot.func.auth import check_password
from bot.states.fsm import Auth, AuthUser
from config.config import BOT_API_TOKEN, filesharings
from kb.main_menu import main_menu_keyboard
from map.files import create_new_user
from map.main import create_html
from map.parsing import get_imgs
from ocr.main import check_img

dp = Dispatcher()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserTask:
    message: Message
    user_id: int
    url: str
    coord_status: bool


user_queues: dict[int, deque[UserTask]] = {}
user_workers: dict[int, asyncio.Task] = {}
user_queue_lock = asyncio.Lock()

FILES_FM_DOWNLOAD_URL = "http://fv5-3.failiem.lv/server_scripts/zip/zip_streamer/upload_zip_streamer.php"
FILES_FM_DOMAINS = {"files.fm", "ru.files.fm", "ru.files.me", "files.me"}
SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tiff",
}
STATIC_SERVER_PORT = 8765
MAP_ROOT_PATH = Path("map/generate_map").resolve()

static_server_runner: web.AppRunner | None = None


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

    supported_url = extract_supported_url(message.text or "")
    if supported_url:
        await check_function(message=message, state=state, url=supported_url)
    else:
        await message.reply("В сообщени нет ссылки поддерживаемой нашим ботом")


async def check_function(message: Message, state: FSMContext, url: str):
    """Ставит ссылку пользователя в очередь на обработку"""
    data = await state.get_data()
    if not data.get("coord_status"):
        await state.update_data(coord_status=False)
        data = await state.get_data()

    queued_before = await enqueue_user_task(
        message=message,
        url=url,
        coord_status=data.get("coord_status", False),
    )

    if queued_before > 0:
        await message.reply(
            f"Ссылка поставлена в очередь. Перед вами задач: {queued_before}."
        )


async def enqueue_user_task(
    message: Message, url: str, coord_status: bool
) -> int:
    """Добавляет задачу пользователя в очередь и запускает воркер при необходимости."""
    user_id = message.from_user.id
    task = UserTask(
        message=message,
        user_id=user_id,
        url=url,
        coord_status=coord_status,
    )

    async with user_queue_lock:
        queue = user_queues.setdefault(user_id, deque())
        worker = user_workers.get(user_id)
        worker_running = worker is not None and not worker.done()

        queue.append(task)
        queued_before = len(queue) if worker_running else len(queue) - 1

        if not worker_running:
            user_workers[user_id] = asyncio.create_task(
                process_user_queue(user_id)
            )

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
        embedded_image_map: dict[str, str] = {}
        if is_files_fm_url(task.url):
            logger.info(
                "Начата обработка files.fm ссылки user=%s url=%s",
                task.user_id,
                task.url,
            )
            img_urls, embedded_image_map = await get_imgs_from_files_fm(
                url=task.url,
                user=task.user_id,
            )
        else:
            img_urls = await get_imgs(url=task.url, user=task.user_id)

        if not img_urls:
            raise ValueError("Не удалось получить изображения по ссылке")

        await msg.edit_text(" ✅Изображения получены, получаем координаты...")

        result = await check_img(
            img_urls=img_urls, coord_status=task.coord_status
        )
        await msg.edit_text(" ✅Координаты получены, создаём карту...")

        processed_coords = result[0]
        processed_urls = set(processed_coords.keys())
        unprocessed_urls = [
            url for url in img_urls if url not in processed_urls
        ]

        if embedded_image_map:
            processed_coords = {
                embedded_image_map.get(url, url): coord
                for url, coord in processed_coords.items()
            }

        await create_html(coords=processed_coords, user=task.user_id)
        await safe_delete_message(msg)

        await task.message.reply_document(
            FSInputFile(
                path=f"map/generate_map/{str(task.user_id)}/leaflet.html"
            ),
            caption=f"Готово ✅, {result[-1]}",
        )

        if unprocessed_urls:
            links_message = "📸 Необработанные изображения:\n"
            for i, url in enumerate(unprocessed_urls, 1):
                link_or_name = extract_filename_from_local_url(url)
                links_message += f"{i}. {link_or_name}\n"

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
        assert worker is not None
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


async def send_long_message(
    text: str, message: Message, max_length: int = 4000
):
    """Отправка длинного сообщения с разбивкой на части"""
    parts = []

    # Разбиваем текст на части по max_length символов
    while len(text) > max_length:
        # Ищем последнюю новую строку в пределах max_length
        split_pos = text.rfind("\n", 0, max_length)
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


def extract_supported_url(text: str) -> str | None:
    """Извлекает первую поддерживаемую ссылку из текста."""
    urls = re.findall(r"https?://[^\s]+", text)
    for raw_url in urls:
        url = raw_url.rstrip(".,);]>\"'")
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if any(filesharing in host for filesharing in filesharings):
            return url
        if is_files_fm_url(url):
            return url
    return None


def is_files_fm_url(url: str) -> bool:
    """Проверка, что ссылка относится к files.fm."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    return host in FILES_FM_DOMAINS or host.endswith(".files.fm")


def extract_files_fm_hash(url: str) -> str | None:
    """Извлекает uhash из ссылки вида /u/<hash>."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "u" and index + 1 < len(parts):
            return parts[index + 1]
    return None


async def download_files_fm_zip(
    uhash: str, user: int, retries: int = 3
) -> Path:
    """Скачивает ZIP с files.fm, при необходимости повторяет попытку."""
    user_temp_dir = MAP_ROOT_PATH / str(user) / "temp" / "files_fm"
    user_temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = user_temp_dir / f"{uhash}.zip"
    params = {"uhash": uhash}

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(1, retries + 1):
            async with session.get(
                FILES_FM_DOWNLOAD_URL, params=params
            ) as response:
                content = await response.read()
                content_type = response.headers.get("Content-Type", "").lower()
                is_zip = content.startswith(b"PK") or "zip" in content_type
                logger.info(
                    "files.fm попытка=%s/%s uhash=%s status=%s content_type=%s final_url=%s is_zip=%s",
                    attempt,
                    retries,
                    uhash,
                    response.status,
                    content_type,
                    response.url,
                    is_zip,
                )

                if response.status == 200 and is_zip:
                    await asyncio.to_thread(zip_path.write_bytes, content)
                    logger.info(
                        "ZIP получен и сохранен user=%s uhash=%s path=%s bytes=%s",
                        user,
                        uhash,
                        zip_path,
                        len(content),
                    )
                    return zip_path

            if attempt < retries:
                logger.warning(
                    "Получен не-ZIP ответ, повторяем загрузку uhash=%s через 1с",
                    uhash,
                )
                await asyncio.sleep(1)

    raise ValueError(
        "Не удалось получить ZIP с files.fm после повторных попыток"
    )


async def extract_images_from_zip(
    zip_path: Path, user: int, uhash: str
) -> list[Path]:
    """Распаковывает ZIP и возвращает список файлов изображений."""
    extract_dir = MAP_ROOT_PATH / str(user) / "temp" / "files_fm" / uhash
    extract_dir.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(unzip_archive, zip_path, extract_dir)
    image_paths = sorted(
        file_path
        for file_path in extract_dir.rglob("*")
        if file_path.is_file()
        and file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )
    logger.info(
        "ZIP распакован user=%s uhash=%s images_found=%s dir=%s",
        user,
        uhash,
        len(image_paths),
        extract_dir,
    )
    return image_paths


def unzip_archive(zip_path: Path, extract_dir: Path):
    """Распаковка архива в отдельный поток."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)


async def ensure_static_server():
    """Поднимает локальный сервер для выдачи распакованных файлов."""
    global static_server_runner

    if static_server_runner is not None:
        return

    app = web.Application()
    app.router.add_static("/files", str(MAP_ROOT_PATH), show_index=False)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", STATIC_SERVER_PORT)
    await site.start()
    static_server_runner = runner
    logger.info(
        "Запущен static server для files.fm на 127.0.0.1:%s",
        STATIC_SERVER_PORT,
    )


def local_file_path_to_url(file_path: Path) -> str:
    """Преобразует локальный путь к файлу в URL локального сервера."""
    relative_path = file_path.resolve().relative_to(MAP_ROOT_PATH).as_posix()
    return (
        f"http://127.0.0.1:{STATIC_SERVER_PORT}/files/{quote(relative_path)}"
    )


def extract_filename_from_local_url(url: str) -> str:
    """Возвращает имя файла из локального URL."""
    path = urlparse(url).path
    filename = Path(path).name
    return filename or url


def image_path_to_base64_data_url(
    image_path: Path,
    max_side: int = 1280,
    jpeg_quality: int = 72,
) -> str:
    """Сжимает изображение и кодирует в base64 data URL."""
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


async def build_embedded_image_map(
    image_paths: list[Path],
) -> dict[str, str]:
    """Строит словарь local_url -> base64 data URL для карты."""
    result: dict[str, str] = {}
    for image_path in image_paths:
        local_url = local_file_path_to_url(image_path)
        data_url = await asyncio.to_thread(
            image_path_to_base64_data_url, image_path
        )
        result[local_url] = data_url
    return result


async def get_imgs_from_files_fm(
    url: str, user: int
) -> tuple[list[str], dict[str, str]]:
    """Получает изображения из files.fm через ZIP архив."""
    uhash = extract_files_fm_hash(url)
    if not uhash:
        raise ValueError("Не удалось извлечь идентификатор ссылки files.fm")

    zip_path = await download_files_fm_zip(uhash=uhash, user=user)
    image_paths = await extract_images_from_zip(
        zip_path=zip_path, user=user, uhash=uhash
    )
    if not image_paths:
        logger.warning(
            "После распаковки нет изображений user=%s uhash=%s", user, uhash
        )
        return []

    await ensure_static_server()
    result_urls = [local_file_path_to_url(path) for path in image_paths]
    embedded_image_map = await build_embedded_image_map(image_paths)
    logger.info(
        "Подготовлены ссылки для OCR и base64 для карты user=%s uhash=%s count=%s",
        user,
        uhash,
        len(result_urls),
    )
    return result_urls, embedded_image_map


async def run_bot():
    """Запуск бота"""

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)
