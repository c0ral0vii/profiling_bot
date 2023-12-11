import aiohttp
import os
import uuid

from bs4 import BeautifulSoup
from config.config import imgs_dir
from ocr.main import check_img
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

    delete_imgs()

    page = await get_page(url=url)

    soup = BeautifulSoup(page, 'lxml')

    if url.find('files.fm'):
        # files.fm
        all_links = soup.find_all('a', class_='top_button_download')

        for text in all_links:
            finally_link = text.get('href')
            await filesfm_download_image(img_url=finally_link)
        
    
    if url.find('postimg.cc'):
        # postimg
        img_links = soup.find_all('a', class_='img')

        for text in img_links:
            link = text.get('href')
            print(link)

            # Получение ссылки для скачивания

            img_page = await get_page(url=link)
            img_soup = BeautifulSoup(img_page, 'lxml')
            tag = img_soup.find('a', id='download')
            finally_link = tag.get('href')
            print(finally_link)

            await postimg_download_image(finally_link)
        
        # Получение координат
        return check_img()


async def postimg_download_image(img_url: str):
    '''Загрузка фотографий с postimg в папку temp'''

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                img_data = await resp.read()
    except Exception as e:
        print(f"An error occurred: {e}")
    
    filename = 'image_' + str(uuid.uuid4()) + '.jpg'
    file_path = os.path.join(imgs_dir, filename)

    with open(file_path, 'wb') as img:
        img.write(img_data)
    
    return

async def filesfm_download_image():
    '''Загрузка фотографий с filesfm в папку temp'''

    ...