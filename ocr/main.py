import numpy as np
import re
import urllib.request
import ssl

from io import BytesIO
from paddleocr import PaddleOCR
from multiprocessing import Pool
from PIL import Image


ocr = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def process_img(img_urls: str = 'https://i.postimg.cc/BQV7JDh7/29-23-18-29-s.jpg') -> dict:
    '''Обработка фотографии'''

    with urllib.request.urlopen(img_urls, context=ctx) as u:
        raw_data = u.read()

    img = Image.open(BytesIO(raw_data))
    img = img.convert('L')
    img = np.array(img)

    result = ocr.ocr(img, cls=True)

    two_cords = []
    coordinates = {}

    for line in result:
        for word_info in line:
            word = word_info[1][0]
            coord = re.findall(r'(\s*\d{2,}\.\d{4,6}\s*)', word)
            print(word)
            try:
                if 'N' in word and len(word) >= 15:
                    # Для координат типа 404956184N39.71779004E+5,90m
                    coords = word.split('N')
                    ready_cords = []
                    for i in coords:
                        i = i.replace('.', '')
                        coord = i[0:2] + '.' + i[2:8]
                        ready_cords.append(coord)
                    coordinates[img_urls] = ready_cords
                    continue

                if len(word) >= 12 and word.count('.') == 2 and word.replace('.', '', 1).replace('.', '', 1).isnumeric() and word.count(',') == 0:
                    for i in [word]:
                        index_second_dot = i.find('.', i.find('.') + 1)
                        first_coord = i[:index_second_dot - 2]
                        second_coord = i[index_second_dot - 2:]
                        coordinates[img_urls] = [first_coord, second_coord[:8]]
                        continue

                if len(coord) == 2:
                    coordinates[img_urls] = coord
                    continue

                if len(coord) == 1:
                    two_cords.append(coord)
                    continue
            except Exception as _ex:
                print(_ex)
                continue

    for _ in two_cords:
        ready_coords = []
        for cord in two_cords:
            ready_coords.append(*cord)
        coordinates.setdefault(img_urls, ready_coords)
    
    return coordinates


def check_img(img_urls: list) -> dict:
    '''PaddleOCR смотрит фотографию и ищет координаты на нём'''

    with Pool(processes=1) as pool:
        results = pool.map(process_img, img_urls)

    coordinates = {k: v for result in results for k, v in result.items()}
    print(len(coordinates))
    return coordinates

print(process_img())