import aiohttp
import asyncio
import re
import uuid
import os
import cv2

from paddleocr import PPStructure, draw_structure_result, save_structure_res
from PIL import Image
from bs4 import BeautifulSoup

from config.config import filesharings
draw_structure_result,save_structure_res
imgs_dir = 'map/temp/imgs/'


async def check_filesharing(text: str, user):
    '''Проверка является ли текст файлообменником'''

    regular = r'\b(?:{})\b'.format('|'.join(filesharings))
    result = re.search(regular, text)
    if result:
        await get_imgs(url=text)
        url = 'Готово'
        return url
    else:
        return 'Ссылка указана неверно'


async def get_imgs(url: str):
    '''Получение фотографий с файлообменника'''

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            page = await response.text()

    await delete_imgs()

    soup = BeautifulSoup(page, features='lxml')
    imgs = soup.find_all('a', class_='thumb')

    try:
        for div in imgs:
            if div.img:
                img_url = div.img.get('src')
                await download_images(img_url=img_url)

            else:
                img_style = div.a.get('style')
                img_url = re.findall(r"'(.*?)'", img_style)[0]

                await download_images(img_url=img_url)
    except:
        return 'У файлов нет ссылки'


async def download_images(img_url: str):
    '''Загрузка фотографий в папку temp'''

    filename = 'image_' + str(uuid.uuid4()) + '.jpg'
    file_path = os.path.join(imgs_dir, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(img_url) as response:
            img_data = await response.read()

    with open(file_path, 'wb') as img:
        img.write(img_data)


async def delete_imgs():
    '''Удаление фотографий из папки temp'''

    for file in os.listdir(imgs_dir):
        os.remove(os.path.join(imgs_dir, file))


async def check_imgs():
    '''ИИ проверяет фотографии'''

    img_path = imgs_dir + 'hz.jpg'
    table_engine = PPStructure()
    img = cv2.imread(img_path)
    result = table_engine(img)
    print(result)


async def generate_map():
    ...