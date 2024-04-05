import numpy as np
import re
import urllib.request
import ssl

from io import BytesIO
from easyocr import Reader
from multiprocessing.dummy import Pool
from PIL import Image

ssl._create_default_https_context = ssl._create_unverified_context
reader = Reader(['en'], gpu=False)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def process_img(img_urls: str) -> dict:
    '''Обработка фотографии'''

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
        coord = re.findall(r'(\d{2,}[.,]\d{4,6})', word)

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

    return coordinates


def check_img(img_urls: list) -> dict:
    '''EasyOCR смотрит фотографию и ищет координаты на нём'''

    with Pool(processes=2) as pool:
        results = pool.map(process_img, img_urls)

    coordinates = {k: v for result in results for k, v in result.items()}

    return [coordinates, f'{len(coordinates)}/{len(img_urls)}']