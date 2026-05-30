import asyncio
import base64
import logging
import re
import shutil
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

FILES_FM_DOWNLOAD_URL = "https://fv5-3.failiem.lv/server_scripts/zip/zip_streamer/upload_zip_streamer.php"
FILES_FM_DOWNLOAD_TIMEOUT = 900
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
# Лимит Bot API при upload через multipart/form-data — 50 MB.
TELEGRAM_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAP_MAX_SIZE_BYTES = 48 * 1024 * 1024
MAP_HTML_OVERHEAD_BYTES = 512 * 1024

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
        local_url_to_path: dict[str, Path] = {}
        if is_files_fm_url(task.url):
            logger.info(
                "Начата обработка files.fm ссылки user=%s url=%s",
                task.user_id,
                task.url,
            )
            img_urls, local_url_to_path = await get_imgs_from_files_fm(
                url=task.url,
                user=task.user_id,
            )
        else:
            img_urls = await get_imgs(url=task.url, user=task.user_id)

        if not img_urls:
            raise ValueError("Не удалось получить изображения по ссылке")

        await msg.edit_text(
            f" ✅Изображений: {len(img_urls)}, получаем координаты..."
        )

        result = await check_img(
            img_urls=img_urls, coord_status=task.coord_status
        )
        await msg.edit_text(" ✅Координаты получены, создаём карту...")

        processed_coords = result[0]
        processed_urls = set(processed_coords.keys())
        unprocessed_urls = [
            url for url in img_urls if url not in processed_urls
        ]
        original_coords = dict(processed_coords)
        map_path = Path(f"map/generate_map/{task.user_id}/leaflet.html")

        if local_url_to_path:
            processed_coords, map_path = await ensure_map_within_size_limit(
                user_id=task.user_id,
                original_coords=original_coords,
                local_url_to_path=local_url_to_path,
                coords_urls=list(original_coords.keys()),
            )
        else:
            await create_html(coords=processed_coords, user=task.user_id)

        map_size_mb = map_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Карта создана user=%s size_mb=%.2f",
            task.user_id,
            map_size_mb,
        )
        await safe_delete_message(msg)

        caption = f"Готово ✅, {result[-1]}"
        if map_size_mb > 30:
            caption += f" (карта {map_size_mb:.0f} MB)"

        await send_map_document(
            message=task.message,
            map_path=map_path,
            caption=caption,
        )
    except asyncio.CancelledError:
        await safe_delete_message(msg)
        raise
    except Exception as e:
        await safe_delete_message(msg)
        await task.message.answer(
            f"Произошла ошибка при обработке, повторите попытку ({e})"
        )
    finally:
        await asyncio.to_thread(cleanup_user_temp_dir, task.user_id)


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
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://ru.files.fm/u/{uhash}",
    }

    timeout = aiohttp.ClientTimeout(total=FILES_FM_DOWNLOAD_TIMEOUT)
    async with aiohttp.ClientSession(
        timeout=timeout, headers=headers
    ) as session:
        for attempt in range(1, retries + 1):
            if zip_path.exists():
                zip_path.unlink()

            async with session.get(
                FILES_FM_DOWNLOAD_URL,
                params=params,
                allow_redirects=False,
            ) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                logger.info(
                    "files.fm попытка=%s/%s uhash=%s status=%s content_type=%s url=%s",
                    attempt,
                    retries,
                    uhash,
                    response.status,
                    content_type,
                    response.url,
                )

                if response.status != 200:
                    if attempt < retries:
                        await asyncio.sleep(1)
                    continue

                downloaded_bytes, prefix = await stream_response_to_file(
                    response, zip_path
                )
                is_zip = prefix.startswith(b"PK")
                logger.info(
                    "files.fm загрузка завершена uhash=%s bytes=%s is_zip=%s",
                    uhash,
                    downloaded_bytes,
                    is_zip,
                )

                if is_zip and downloaded_bytes > 0:
                    logger.info(
                        "ZIP получен и сохранен user=%s uhash=%s path=%s bytes=%s",
                        user,
                        uhash,
                        zip_path,
                        downloaded_bytes,
                    )
                    return zip_path

                if zip_path.exists():
                    zip_path.unlink()

            if attempt < retries:
                logger.warning(
                    "Получен не-ZIP ответ, повторяем загрузку uhash=%s через 1с",
                    uhash,
                )
                await asyncio.sleep(1)

    raise ValueError(
        "Не удалось получить ZIP с files.fm после повторных попыток"
    )


async def stream_response_to_file(
    response: aiohttp.ClientResponse, file_path: Path
) -> tuple[int, bytes]:
    """Сохраняет HTTP-ответ в файл потоком и возвращает размер и префикс."""
    downloaded_bytes = 0
    prefix = b""

    with file_path.open("wb") as file:
        async for chunk in response.content.iter_chunked(1024 * 1024):
            if not chunk:
                continue
            if not prefix:
                prefix = chunk[:4]
            file.write(chunk)
            downloaded_bytes += len(chunk)

    return downloaded_bytes, prefix


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
    """Распаковка архива с защитой от Zip Slip."""
    extract_root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target_path = (extract_root / member.filename).resolve()
            if not target_path.is_relative_to(extract_root):
                raise ValueError(
                    f"Небезопасный путь в архиве: {member.filename}"
                )
            archive.extract(member, path=extract_root)


def cleanup_user_temp_dir(user_id: int):
    """Удаляет временные файлы пользователя после обработки."""
    temp_dir = MAP_ROOT_PATH / str(user_id) / "temp"
    if not temp_dir.exists():
        return

    shutil.rmtree(temp_dir)
    logger.info("Очищена temp директория user=%s path=%s", user_id, temp_dir)


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


def placeholder_data_url(source: str) -> str:
    """Миниатюра-заглушка, если фото не удалось встроить в карту."""
    label = extract_filename_from_local_url(source)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="140" height="180">'
        f'<rect width="100%" height="100%" fill="#222"/>'
        f'<text x="10" y="90" fill="#ccc" font-size="12">{label[:24]}</text>'
        f"</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def image_path_to_base64_within_budget(
    image_path: Path, max_bytes: int
) -> str:
    """Подбирает сжатие так, чтобы data URL уложился в лимит."""
    if max_bytes < 300:
        return placeholder_data_url(image_path.name)

    presets = [
        (1280, 72),
        (960, 65),
        (800, 58),
        (640, 50),
        (480, 42),
        (360, 35),
        (240, 28),
    ]
    smallest = ""
    for max_side, quality in presets:
        data_url = image_path_to_base64_data_url(
            image_path, max_side=max_side, jpeg_quality=quality
        )
        smallest = data_url
        if len(data_url.encode("utf-8")) <= max_bytes:
            return data_url

    return smallest or placeholder_data_url(image_path.name)


async def build_embedded_image_map(
    local_url_to_path: dict[str, Path],
    urls_to_embed: list[str],
    image_budget: int | None = None,
) -> dict[str, str]:
    """Строит base64 data URL для карты с учётом лимита Telegram (48 MB)."""
    embed_urls = [url for url in urls_to_embed if url in local_url_to_path]
    if not embed_urls:
        return {}

    if image_budget is None:
        image_budget = MAP_MAX_SIZE_BYTES - MAP_HTML_OVERHEAD_BYTES
    per_image_budget = max(image_budget // len(embed_urls), 8 * 1024)

    result: dict[str, str] = {}
    for url in embed_urls:
        data_url = await asyncio.to_thread(
            image_path_to_base64_within_budget,
            local_url_to_path[url],
            per_image_budget,
        )
        result[url] = data_url

    total_size = sum(len(value.encode("utf-8")) for value in result.values())
    while total_size > image_budget and per_image_budget > 4 * 1024:
        per_image_budget = int(per_image_budget * 0.85)
        for url in embed_urls:
            result[url] = await asyncio.to_thread(
                image_path_to_base64_within_budget,
                local_url_to_path[url],
                per_image_budget,
            )
        total_size = sum(
            len(value.encode("utf-8")) for value in result.values()
        )

    logger.info(
        "Base64 для карты: images=%s budget_mb=%.1f total_mb=%.1f per_image_kb=%.0f",
        len(embed_urls),
        image_budget / (1024 * 1024),
        total_size / (1024 * 1024),
        per_image_budget / 1024,
    )
    return result


def apply_embedded_images(
    original_coords: dict[str, list],
    embedded_image_map: dict[str, str],
) -> dict[str, list]:
    """Подставляет base64 data URL вместо локальных ссылок в координатах."""
    return {
        embedded_image_map.get(url, placeholder_data_url(url)): coord
        for url, coord in original_coords.items()
    }


async def ensure_map_within_size_limit(
    user_id: int,
    original_coords: dict[str, list],
    local_url_to_path: dict[str, Path],
    coords_urls: list[str],
) -> tuple[dict[str, list], Path]:
    """Пересжимает карту, пока HTML не влезет в лимит Telegram."""
    map_path = MAP_ROOT_PATH / str(user_id) / "leaflet.html"
    budgets = [
        MAP_MAX_SIZE_BYTES - MAP_HTML_OVERHEAD_BYTES,
        int((MAP_MAX_SIZE_BYTES - MAP_HTML_OVERHEAD_BYTES) * 0.75),
        int((MAP_MAX_SIZE_BYTES - MAP_HTML_OVERHEAD_BYTES) * 0.55),
        int((MAP_MAX_SIZE_BYTES - MAP_HTML_OVERHEAD_BYTES) * 0.4),
    ]

    processed_coords: dict[str, list] = {}
    for budget in budgets:
        embedded_image_map = await build_embedded_image_map(
            local_url_to_path=local_url_to_path,
            urls_to_embed=coords_urls,
            image_budget=budget,
        )
        processed_coords = apply_embedded_images(
            original_coords, embedded_image_map
        )
        await create_html(coords=processed_coords, user=user_id)
        if map_path.stat().st_size <= MAP_MAX_SIZE_BYTES:
            return processed_coords, map_path

        logger.warning(
            "Карта %.1f MB > лимита %.1f MB, budget=%.0f KB",
            map_path.stat().st_size / (1024 * 1024),
            MAP_MAX_SIZE_BYTES / (1024 * 1024),
            budget / 1024,
        )

    return processed_coords, map_path


def prepare_map_upload_path(map_path: Path) -> Path:
    """Готовит файл для отправки в Telegram (при необходимости упаковывает в ZIP)."""
    if map_path.stat().st_size <= TELEGRAM_MAX_DOCUMENT_BYTES:
        return map_path

    zip_path = map_path.with_suffix(".html.zip")
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(map_path, arcname="leaflet.html")

    if zip_path.stat().st_size <= TELEGRAM_MAX_DOCUMENT_BYTES:
        return zip_path

    zip_path.unlink(missing_ok=True)
    return map_path


async def send_map_document(
    message: Message, map_path: Path, caption: str
) -> None:
    """Отправляет карту пользователю с учётом лимита 50 MB Bot API."""
    send_path = await asyncio.to_thread(prepare_map_upload_path, map_path)
    file_size = send_path.stat().st_size
    size_mb = file_size / (1024 * 1024)

    if file_size > TELEGRAM_MAX_DOCUMENT_BYTES:
        await message.answer(
            "Карта готова, но слишком большая для отправки в Telegram "
            f"({size_mb:.1f} MB, лимит 50 MB).\n"
            "Попробуйте архив с меньшим числом фотографий — "
            "в Telegram встраиваются только снимки с найденными координатами."
        )
        logger.error(
            "Не удалось отправить карту: size_mb=%.2f path=%s",
            size_mb,
            send_path,
        )
        return

    if send_path.suffix == ".zip":
        caption += " (архив ZIP, распакуйте leaflet.html)"

    await message.reply_document(
        FSInputFile(path=str(send_path)),
        caption=caption,
    )


async def get_imgs_from_files_fm(
    url: str, user: int
) -> tuple[list[str], dict[str, Path]]:
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
        return [], {}

    await ensure_static_server()
    result_urls = [local_file_path_to_url(path) for path in image_paths]
    local_url_to_path = {
        local_file_path_to_url(path): path for path in image_paths
    }
    logger.info(
        "Подготовлены ссылки для OCR user=%s uhash=%s count=%s",
        user,
        uhash,
        len(result_urls),
    )
    return result_urls, local_url_to_path


async def run_bot():
    """Запуск бота"""

    bot = Bot(BOT_API_TOKEN)

    await dp.start_polling(bot)
