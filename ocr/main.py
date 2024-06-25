import numpy as np
import re
import urllib.request
import ssl
import datetime
import asyncio

from io import BytesIO
from easyocr import Reader
from multiprocessing.dummy import Pool
from PIL import Image

ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

pool_instance = None


def process_img(img_urls: str, reader) -> dict:
    '''Обработка фотографии'''

    current_time = datetime.datetime.today()

    with urllib.request.urlopen(img_urls, context=ctx) as u:
        raw_data = u.read()

    img = Image.open(BytesIO(raw_data))
    img = img.convert('L')
    img = np.array(img)

    result = reader.readtext(img)

    two_cords = []
    coordinates = {}

    for line in result:
        word = line[1]
        coord = re.findall(r'([1-9]\d[.,]\d{4,6})', word)
        print(word, coord)
        if len(coord) == 2:
            coord[0] = coord[0].replace(',', '.')
            coord[-1] = coord[-1].replace(',', '.')

            coordinates[img_urls] = coord
            continue

        if len(coord) == 1:
            two_cords.append(coord)
            continue

    for _ in two_cords:
        ready_coords = []
        for cord in two_cords:
            ready_coords.append(*cord)
        coordinates.setdefault(img_urls, ready_coords)

    print(coordinates)
    return coordinates


async def check_img(img_urls: list) -> dict:
    '''EasyOCR смотрит фотографию и ищет координаты на нём'''

    reader = Reader(['en'], gpu=False)

    with Pool(processes=3) as pool:
        results = pool.map(process_img, img_urls, reader)

    coordinates = {k: v for result in results for k, v in result.items()}

    return [coordinates, f'{len(coordinates)}/{len(img_urls)}']
