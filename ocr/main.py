import numpy as np
import re
from paddleocr import PaddleOCR
from multiprocessing import Pool
from PIL import Image, ImageOps
from map.files import check_files

ocr = PaddleOCR(use_angle_cls=True, lang='en')

def process_img(img_path):
    img = Image.open(img_path)
    if isinstance(img, np.ndarray):
        img = Image.fromarray(img)
    img = ImageOps.invert(img.convert('RGB'))
    result = ocr.ocr(np.array(img), cls=True)
    two_cords = []
    coordinates = {}
    for line in result:
        for word_info in line:
            coord = re.findall(r'(\s*\d{2,}\.\d{4,6}\s*)', word_info[1][0])
            if len(coord) == 2:
                coordinates[img_path] = coord
            if len(coord) == 1:
                two_cords.append(coord)
    for coord in two_cords:
        ready_coords = []
        for cord in two_cords:
            ready_coords.append(*cord)
        coordinates.setdefault(img_path, ready_coords)
    return coordinates


def check_img(user: str) -> dict:
    '''PaddleOCR смотрит фотографию и ищит координаты на нём'''
    imgs_path = check_files(user=user)
    with Pool(processes=2) as pool:
        results = pool.map(process_img, imgs_path)
    coordinates = {k: v for result in results for k, v in result.items()}
    return coordinates
