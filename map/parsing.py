import aiofiles
import aiohttp
import time

from bs4 import BeautifulSoup
from .download import get_source_html


async def get_page(url: str):
    """Получение страницы"""

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(verify_ssl=False)
    ) as session:
        async with session.get(url) as response:
            try:
                page = await response.text()
            except Exception:
                return None
            finally:
                await session.close()
    return page


async def get_imgs(url: str, user: int):
    """Получение фотографий с файлообменника"""

    try:
        async with aiofiles.open(
            await get_source_html(url=url, user=user), "r", encoding="utf-8"
        ) as f:
            soup = BeautifulSoup(await f.read(), "lxml")

    except Exception as ex:
        print(f"Ошибка: {ex}")
        return

    img_urls = []

    # postimg
    img_links = soup.find_all("a", class_="img")

    for text in img_links:
        if text.get("href")[0] != "h":
            correct_url = "https:" + text.get("href")
        else:
            correct_url = text.get("href")
        img_page = await get_page(url=correct_url)
        if img_page == None:
            continue
        img_soup = BeautifulSoup(img_page, "lxml")
        try:
            finally_link = img_soup.find("img", class_="zoom").get("src")
        except:
            finally_link = img_soup.find("div", class_="image-outer").img.get("src")
        img_urls.append(finally_link)

    return img_urls
