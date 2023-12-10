import cv2
import numpy as np
from paddleocr import PaddleOCR
from PIL import Image, ImageOps

from map.files import check_files


def check_img() -> list:
    '''PaddleOCR смотрит фотографию и ищит координаты на нём'''

    # Создаем экземпляр OCR
    ocr = PaddleOCR(lang='en')

    # Открываем изображение
    img_path = 'ocr/image_61ac4701-0acb-4b65-aae3-183cab648167.jpg'
    img = Image.open(img_path)

    # Проверяем, является ли изображение экземпляром np.ndarray
    if isinstance(img, np.ndarray):
        # Если это так, преобразуем его в PIL Image
        img = Image.fromarray(img)

    # Инвертируем цвета изображения
    img = ImageOps.invert(img.convert('RGB'))

    # Сохраняем обработанное изображение
    img.save('inverted_image.png')

    # Применяем OCR к изображению
    result = ocr.ocr(np.array(img))

    # Ищем координаты в результате
    coordinates = []
    for line in result:
        for word_info in line:
            print(word_info)

    print(coordinates)

