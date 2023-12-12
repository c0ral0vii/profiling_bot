import numpy as np
import re
import os

from paddleocr import PaddleOCR
from PIL import Image, ImageOps

from map.files import check_files, create_coordinate_file, change_img_name
from config.config import imgs_dir

def check_img(imgs_path=check_files()) -> list:
    '''PaddleOCR смотрит фотографию и ищит координаты на нём'''

    ocr = PaddleOCR(lang='en')
    coordinates = {}
    for img_path in imgs_path:
        img = Image.open(img_path)

        if isinstance(img, np.ndarray):
            img = Image.fromarray(img)

        img = ImageOps.invert(img.convert('RGB'))

        # Сохраняем обработанное изображение, включить для проверки
        # img.save('inverted_image.png')

        result = ocr.ocr(np.array(img), cls=False, rec=True)

        # Ищем координаты в результате
        two_cords = []

        print(img_path)
        for line in result:
            for word_info in line:
                coord = re.findall(r'(\s*\d{2,}\.\d{4,6}\s*)', word_info[1][0])
                print(len(coord))
                if len(coord) == 2:
                    coordinates.setdefault(img_path, coord)
                if len(coord) == 1:
                    two_cords.append(coord)
        
        for coord in two_cords:
            ready_coords = []
            for cord in two_cords:
                ready_coords.append(*cord)
            coordinates.setdefault(img_path, ready_coords)
            
    print(coordinates)
    # correct_coordinates = replace_cords(cords=coordinates)

    create_coordinate_file(cords=coordinates)
    
    return


def replace_cords(cords: dict) -> dict:
    '''Превращение кординат вида (xx.xx.xx.xx) в (xx.xx, xx.xx)'''

    ready_cords = {}

    for key, coord in cords.items():
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', coord):
            parts = coord.split('.')
            correct_coord = parts[0] + '.' + parts[1] + ',' + parts[2] + '.' + parts[3]
            ready_cords.setdefault(key, correct_coord)
        else:
            ready_cords.setdefault(key, correct_coord)
    
    print(ready_cords)
    return ready_cords
