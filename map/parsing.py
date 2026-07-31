import re
from urllib.parse import parse_qs, quote, urlparse

import aiofiles
import aiohttp
from bs4 import BeautifulSoup

from .download import get_source_html

FIVESEK_API_BASE = "https://5sek.cc/api/storage"
FIVESEK_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".gif",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
}
FIVESEK_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".webm",
    ".m4v",
    ".avi",
    ".mkv",
}
ALBUM_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


async def get_page(url: str):
    """Получение HTML страницы по URL"""
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(verify_ssl=False)
    ) as session:
        try:
            async with session.get(url) as response:
                response.raise_for_status()  # Проверяем статус ответа
                return await response.text()
        except (aiohttp.ClientError, Exception) as e:
            print(f"Ошибка при получении страницы {url}: {e}")
            return None


async def get_imgs(url: str, user: int):
    """Получение прямых ссылок на изображения с Postimages.org"""
    try:
        # Получаем и сохраняем HTML страницу
        file_path = await get_source_html(url=url, user=user)

        # Открываем сохранённый файл для парсинга
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(await f.read(), "lxml")

    except Exception as ex:
        print(f"Ошибка при обработке HTML файла: {ex}")
        return []

    img_urls = []

    # Если это страница галереи (первая страница)
    if "gallery" in url:
        # Находим все элементы с миниатюрами
        thumb_containers = soup.find_all("div", class_="col")

        for container in thumb_containers:
            # Извлекаем hotlink из data-атрибутов
            hotlink = container.get("data-hotlink")
            image_name = container.get("data-name")
            image_ext = container.get("data-ext")

            if hotlink and image_name and image_ext:
                # Формируем прямую ссылку на изображение (кодируем пробелы)
                encoded_name = quote(f"{image_name}.{image_ext}", safe="")
                img_url = f"https://i.postimg.cc/{hotlink}/{encoded_name}"
                img_urls.append(img_url)

    # Если это страница отдельного изображения (вторая страница)
    else:
        # Способ 1: Ищем в мета-тегах OpenGraph
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_urls.append(og_image["content"])

        # Способ 2: Ищем основной элемент изображения
        main_image = soup.find("img", id="main-image")
        if main_image and main_image.get("src"):
            img_urls.append(main_image["src"])

        # Способ 3: Ищем в поле "Direct link"
        direct_link = soup.find("input", id="code_direct")
        if direct_link and direct_link.get("value"):
            img_urls.append(direct_link["value"])

    # Удаляем дубликаты
    unique_urls = []
    seen = set()
    for url in img_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


def is_5sek_url(url: str) -> bool:
    """Проверка, что ссылка относится к 5sek.cc."""
    host = (urlparse(url).netloc or "").lower()
    return host == "5sek.cc" or host.endswith(".5sek.cc")


def extract_5sek_album_uuid(url: str) -> str | None:
    """Извлекает UUID альбома из ссылки 5sek.cc."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("u", "uuid", "album", "id"):
        values = query.get(key) or []
        if values and ALBUM_UUID_RE.fullmatch(values[0].strip()):
            return values[0].strip()

    path_match = re.search(
        r"/storage/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        parsed.path,
        re.IGNORECASE,
    )
    if path_match:
        return path_match.group(1)

    bare_match = ALBUM_UUID_RE.search(parsed.path)
    if bare_match:
        return bare_match.group(0)

    return None


def _is_image_link(link: str) -> bool:
    """Оставляет только фото-ссылки, видео отбрасывает."""
    path = urlparse(link).path.lower()
    for ext in FIVESEK_VIDEO_EXTENSIONS:
        if path.endswith(ext):
            return False
    for ext in FIVESEK_IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return True
    # Без расширения считаем фото: OCR сам отсеет битые/видео ответы.
    return True


async def get_imgs_from_5sek(url: str) -> list[str]:
    """
    Получает прямые ссылки на фото альбома 5sek.cc через API.
    Файлы не скачиваются локально — только URL, как у postimg.
    """
    album_uuid = extract_5sek_album_uuid(url)
    if not album_uuid:
        raise ValueError("Не удалось извлечь UUID альбома 5sek.cc")

    api_url = f"{FIVESEK_API_BASE}/{album_uuid}/images"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(api_url) as response:
            if response.status == 404:
                raise ValueError("Альбом 5sek.cc не найден")
            if response.status == 410:
                raise ValueError("Срок хранения альбома 5sek.cc истёк")
            response.raise_for_status()
            data = await response.json()

    links = data.get("links") or []
    image_urls = []
    seen = set()
    for link in links:
        if not isinstance(link, str) or not link.strip():
            continue
        clean = link.strip()
        if not _is_image_link(clean):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        image_urls.append(clean)

    return image_urls


class FilesFmParser:
    def __init__(self, url: str):
        self.url = url

    async def get_imgs(self, user: int): ...
