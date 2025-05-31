import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from .download import get_source_html


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
        thumb_containers = soup.find_all("div", class_="thumb-container")
        
        for container in thumb_containers:
            # Извлекаем hotlink из data-атрибутов
            hotlink = container.get("data-hotlink")
            image_name = container.get("data-name")
            image_ext = container.get("data-ext")
            
            if hotlink and image_name and image_ext:
                # Формируем прямую ссылку на изображение
                img_url = f"https://i.postimg.cc/{hotlink}/{image_name}.{image_ext}"
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

    print(unique_urls)    
    return unique_urls
