import asyncio
import re
import ssl
from io import BytesIO
from typing import List, Dict, Union, Tuple, Optional
import aiohttp
import numpy as np
from easyocr import Reader
from PIL import Image, ImageEnhance, ImageFilter
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

pool_instance = None
reader = Reader(["en"], gpu=False)

class DigitCoordinateExtractor:
    def __init__(self):
        # Черный список для фильтрации ложных срабатываний
        self.blacklist_patterns = [
            r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}',  # Даты
            r'\d+\.\d+\+-\d+\.\d+',  # Погрешности 447.86+-3.00
            r'\d+\.\d+[мm]',  # Метры 10.24м
            r'v?\d+\.\d+\.\d+',  # Версии ПО v1.2.3
            r'\d+\.\d+%',  # Проценты
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',  # IP-адреса
        ]

    def enhance_image_quality(self, img: Image.Image) -> np.ndarray:
        """Улучшение качества изображения для лучшего распознавания цифр"""
        try:
            # Увеличение резкости для цифр
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.5)
            
            # Увеличение контраста
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            
            # Легкое размытие для уменьшения шума
            img = img.filter(ImageFilter.MedianFilter(3))
            
            # Конвертация в grayscale
            img = img.convert("L")
            img_array = np.array(img)
            
            # Нормализация контраста
            img_array = self._adaptive_contrast(img_array)
            
            return img_array
        except Exception as e:
            logger.warning(f"Ошибка улучшения изображения: {e}")
            return np.array(img.convert("L"))

    def _adaptive_contrast(self, img_array: np.ndarray) -> np.ndarray:
        """Адаптивное улучшение контраста для цифр"""
        # Простое линейное растяжение гистограммы
        min_val = np.percentile(img_array, 5)
        max_val = np.percentile(img_array, 95)
        
        if max_val > min_val:
            img_array = np.clip((img_array - min_val) * 255.0 / (max_val - min_val), 0, 255)
        
        return img_array.astype(np.uint8)

    def is_plausible_coordinate(self, coord: str) -> bool:
        """Проверка, является ли строка правдоподобной координатой"""
        try:
            num = float(coord)
            
            # Более строгие проверки для координат
            if abs(num) > 180:  # Максимальные значения координат
                return False
                
            # Проверка на минимальную значимость
            if abs(num) < 0.001:
                return False
                
            # Проверка количества знаков после запятой
            parts = coord.split('.')
            if len(parts) == 2 and len(parts[1]) < 3:  # Меньше 3 знаков
                return False
                
            return True
        except ValueError:
            return False

    def is_false_positive(self, text: str, coord: str) -> bool:
        """Проверка на ложное срабатывание"""
        text_lower = text.lower()
        
        # Проверка по черному списку паттернов
        for pattern in self.blacklist_patterns:
            if re.search(pattern, text_lower):
                return True
        
        # Специфичные проверки для координат
        if re.match(r'^\d{1,2}\.\d{1,2}$', coord):  # 10.24 - вероятно не координата
            return True
            
        if re.match(r'^\d+\.0+$', coord):  # 123.000 - подозрительно
            return len(coord) < 8  # Короткие круглые числа вероятно не координаты
            
        return False

    def extract_coordinates_from_digits(self, text: str, coord_status: bool = False) -> List[str]:
        """Извлечение координат из текста, фокусируясь на цифрах"""
        # Более гибкие паттерны для координат
        if coord_status:
            patterns = [
                r'[1-9]\d*[.,]\d{4,8}',  # 30.123456, 1.123456
                r'\d{1,3}[.,]\d{4,8}',   # 123.456789
            ]
        else:
            patterns = [
                r'[1-9]\d[.,]\d{4,8}',   # 30.123456
                r'\d{2,3}[.,]\d{4,8}',   # 123.456789
            ]
        
        all_coords = []
        for pattern in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                coord = match.group()
                # Нормализация формата
                coord = coord.replace(',', '.')
                
                # Проверка на ложное срабатывание
                if self.is_false_positive(text, coord):
                    continue
                    
                # Проверка правдоподобия координаты
                if self.is_plausible_coordinate(coord):
                    all_coords.append(coord)
        
        return all_coords

# Глобальный экземпляр экстрактора
digit_extractor = DigitCoordinateExtractor()

async def process_img(
    img_link: str,
    reader: Reader,
    semaphore: asyncio.Semaphore,
    coord_status: bool = False,
) -> dict | str | None:
    async with semaphore:
        try:
            if "%IMAGE_EXT%" in img_link:
                img_link = img_link.replace("%IMAGE_EXT%", "jpg")

            async with aiohttp.ClientSession() as session:
                async with session.get(img_link, ssl=ctx) as response:
                    if response.status == 200:
                        img_data = await response.read()
                    else:
                        return f"Ошибка - {img_link}"

            img = Image.open(BytesIO(img_data))
            img_processed = digit_extractor.enhance_image_quality(img)

            # Распознавание текста с улучшенными параметрами
            result = reader.readtext(
                img_processed,
                detail=1,
                paragraph=False,
                contrast_ths=0.1,
                adjust_contrast=0.7,
                text_threshold=0.7,
                low_text=0.4,
                link_threshold=0.4
            )

            two_cords = []
            coordinates = {}

            for line in result:
                bbox, text, confidence = line
                
                # Фильтр по уверенности
                if confidence < 0.5:
                    continue
                    
                logger.info(f"Распознано: '{text}' (уверенность: {confidence:.2f})")
                
                # Извлечение координат из текста с помощью улучшенного метода
                coords = digit_extractor.extract_coordinates_from_digits(text, coord_status)
                
                # Логика как в оригинале: если в одной строке найдено 2 координаты, возвращаем их
                if len(coords) == 2:
                    # Нормализация формата
                    coords[0] = coords[0].replace(",", ".")
                    coords[1] = coords[1].replace(",", ".")
                    coordinates[img_link] = coords
                    return {img_link: coords}

                # Если найдена одна координата, сохраняем для возможной пары
                if len(coords) == 1:
                    two_cords.append(coords)

            # Если после обработки всех строк у нас есть 2 одиночные координаты, возвращаем их
            if len(two_cords) >= 2:
                ready_coords = []
                # Берем первые две координаты
                for i in range(2):
                    if two_cords[i]:
                        ready_coords.append(two_cords[i][0].replace(",", "."))
                if len(ready_coords) == 2:
                    return {img_link: ready_coords}

            return None

        except asyncio.TimeoutError:
            return f"Таймаут - {img_link}"
        except Exception as e:
            logger.error(f"Ошибка обработки {img_link}: {str(e)}")
            return f"Ошибка обработки - {img_link}: {str(e)}"


task_list = []


async def check_img(img_urls: list, coord_status: bool = False) -> list:
    """Улучшенный EasyOCR с фокусом на цифрах"""

    semaphore = asyncio.Semaphore(4)
    tasks = [
        asyncio.create_task(process_img(img_link, reader, semaphore, coord_status))
        for img_link in img_urls
    ]

    for task in tasks:
        task_list.append(task)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    coordinates = {}
    for result in results:
        if isinstance(result, Exception):
            print(f"Ошибка: {result}")
        elif isinstance(result, dict):
            coordinates.update(result)
        elif result is not None:
            print(f"Пропущен результат: {result}")

    return [coordinates, f"{len(coordinates)}/{len(img_urls)}"]


async def stop() -> str:
    """Остановка обработки фотографий"""
    if len(task_list) > 0:
        for task in task_list:
            task.cancel()
        return "Остановлено"
    else:
        return "Никаких задач сейчас нет"