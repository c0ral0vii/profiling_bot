import aiohttp
import os

from bs4 import BeautifulSoup
from config.config import imgs_dir, filename, file_path
from .files import delete_imgs


async def get_page(url: str):
    '''Получение страницы, функция чтобы избежать DRY'''

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                page = await response.text()

    return page


async def get_imgs(url: str):
    '''Получение фотографий с файлообменника'''

    await delete_imgs()
    page = await get_page(url=url)

    soup = BeautifulSoup(page, 'lxml')

    if url.find('files.fm'):
        # files.fm
        all_links = soup.find_all('a', class_='top_button_download')

        for text in all_links:
            finally_link = text.get('href')
            await postimg_download_image(img_url=finally_link)
    
    if url.find('postimg.cc'):
        # postimg
        img_links = soup.find_all('a', class_='img')

        for text in img_links:
            link = text.get('href')

            # Получение ссылки для скачивания

            img_page = await get_page(url=link)
            img_soup = BeautifulSoup(img_page, 'lxml')
            tag = img_soup.find('a', id='download')
            finally_link = tag.get('href')

            await postimg_download_image(finally_link)


async def postimg_download_image(img_url: str):
    '''Загрузка фотографий с postimg в папку temp'''

    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as resp:
            img_data = await resp.read()

    with open(file_path, 'wb') as img:
        img.write(img_data)


async def filesfm_download_image():
    '''Загрузка фотографий с filesfm в папку temp'''

    ...