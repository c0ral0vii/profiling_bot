import cv2
import numpy as np
import re

from paddleocr import PaddleOCR
from PIL import Image, ImageOps

from map.files import check_files, create_coordinate_file


def check_img(imgs_path=check_files()) -> list:
    '''PaddleOCR смотрит фотографию и ищит координаты на нём'''

    ocr = PaddleOCR(lang='en')
    coordinates = []

    for img_path in imgs_path:
        img = Image.open(img_path)

        if isinstance(img, np.ndarray):
            img = Image.fromarray(img)

        img = ImageOps.invert(img.convert('RGB'))

        # Сохраняем обработанное изображение, включить для проверки
        # img.save('inverted_image.png')

        result = ocr.ocr(np.array(img), cls=False,rec=True)

        # Ищем координаты в результате
        for line in result:
            for word_info in line:
                print(word_info)
                match = re.search(r'(\d+\.\d+\s*[,\.]\s*\d+\.\d+)', word_info[1][0])
                if match:
                    coordinates.append(match.group(1))

    correct_coordinates = replace_cords(cords=coordinates)

    create_coordinate_file(cords=correct_coordinates)
    
    return


def replace_cords(cords: list) -> True:
    '''Превращение кординат вида (xx.xx.xx.xx) в (xx.xx, xx.xx)'''

    ready_cords = []

    for coord in cords:
        if re.match(r'^\d+\.\d+\.\d+\.\d+$', coord):
            parts = coord.split('.')
            correct_coord = parts[0] + '.' + parts[1] + ', ' + parts[2] + '.' + parts[3]
            ready_cords.append(correct_coord)
        else:
            ready_cords.append(coord)
    
    return ready_cords