import numpy as np
import re
import urllib.request

from io import BytesIO
from paddleocr import PaddleOCR
from multiprocessing import Pool
from PIL import Image


ocr = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=True)


def process_img(img_urls: str) -> dict:
    '''Обработка фотографии'''

    with urllib.request.urlopen(img_urls) as u:
        raw_data = u.read()

    img = Image.open(BytesIO(raw_data))
    img = np.array(img)

    result = ocr.ocr(img, cls=True)

    two_cords = []
    coordinates = {}

    for line in result:
        for word_info in line:
            coord = re.findall(r'(\s*\d{2,}\.\d{4,6}\s*)', word_info[1][0])
            if len(coord) == 2:
                coordinates[img_urls] = coord
            if len(coord) == 1:
                two_cords.append(coord)

    for _ in two_cords:
        ready_coords = []
        for cord in two_cords:
            ready_coords.append(*cord)
        coordinates.setdefault(img_urls, ready_coords)

    return coordinates


def check_img(img_urls: list) -> dict:
    '''PaddleOCR смотрит фотографию и ищет координаты на нём'''

    with Pool(processes=2) as pool:
        results = pool.map(process_img, img_urls)

    coordinates = {k: v for result in results for k, v in result.items()}

    return coordinates
