import ssl
import asyncio
import aiohttp
from PIL import Image
import numpy as np
from io import BytesIO
import re

from easyocr import Reader


ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

pool_instance = None
reader = Reader(['en'], gpu=False)


async def process_img(img_link: str, reader: Reader, semaphore: asyncio.Semaphore):
    async with semaphore:
        async with aiohttp.ClientSession() as session:
            async with session.get(img_link, ssl=ctx) as response:
                if response.status == 200:
                    img_data = await response.read()
                else:
                    return f'Ошибка - {img_link}'

        img = Image.open(BytesIO(img_data))
        img = img.convert('L')
        img = np.array(img)

        result = reader.readtext(img)

        two_cords = []
        coordinates = {}

        for line in result:
            word = line[1]
            coord = re.findall(r'([1-9]\d[.,]\d{4,6})', word)

            if len(coord) == 2:
                coord[0] = coord[0].replace(',', '.')
                coord[-1] = coord[-1].replace(',', '.')

                coordinates[img_link] = coord
                continue

            if len(coord) == 1:
                two_cords.append(coord)
                continue

        for _ in two_cords:
            ready_coords = []
            for cord in two_cords:
                ready_coords.append(*cord)
            coordinates.setdefault(img_link, ready_coords)

        return coordinates

task_list = []

async def check_img(img_urls: list) -> dict:
    '''EasyOCR смотрит фотографию и ищет координаты на нём'''

    semaphore = asyncio.Semaphore(2)
    tasks = [asyncio.create_task(process_img(img_link, reader, semaphore)) for img_link in img_urls]

    for task in tasks:
        task_list.append(task)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    coordinates = {}
    for result in results:
        if isinstance(result, Exception):
            print(f"Ошибка: {result}")
        else:
            coordinates.update(result)

    return [coordinates, f'{len(coordinates)}/{len(img_urls)}']

async def stop():
    '''Остановка обработки фотографий'''
    if len(task_list) > 0:
        for task in task_list:
            task.cancel()
        return 'Остановлено'
    else:
        return 'Никаких задач сейчас нет'