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

class ImprovedCoordinateExtractor:
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
        
        # Белый список контекстных слов
        self.context_words = [
            'coord', 'latitude', 'longitude', 'lat', 'lon', 
            'широта', 'долгота', 'координат', 'gps', 'location'
        ]

    def enhance_image_quality(self, img: Image.Image) -> np.ndarray:
        """Улучшение качества изображения для лучшего распознавания"""
        try:
            # Увеличение резкости
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            
            # Увеличение контраста
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            
            # Легкое размытие для уменьшения шума
            img = img.filter(ImageFilter.MedianFilter(3))
            
            # Конвертация в grayscale
            img = img.convert("L")
            img_array = np.array(img)
            
            return img_array
        except Exception as e:
            logger.warning(f"Ошибка улучшения изображения: {e}")
            return np.array(img.convert("L"))

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

    def extract_all_coordinates(self, text: str, coord_status: bool = False) -> List[str]:
        """Извлечение всех возможных координат из текста"""
        # Основные паттерны для координат
        if coord_status:
            patterns = [
                r'[1-9]+[.,]\d{4,8}',  # 30.123456
            ]
        else:
            patterns = [
                r'[1-9]\d[.,]\d{4,8}',  # 30.123456
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
        
        # Удаление дубликатов с сохранением порядка
        seen = set()
        unique_coords = []
        for coord in all_coords:
            if coord not in seen:
                seen.add(coord)
                unique_coords.append(coord)
                
        return unique_coords

# Глобальный экземпляр улучшенного экстрактора
extractor = ImprovedCoordinateExtractor()

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
            img_processed = extractor.enhance_image_quality(img)

            # Распознавание текста с улучшенными параметрами
            result = reader.readtext(
                img_processed,
                detail=1,
                paragraph=False,
                contrast_ths=0.1,
                adjust_contrast=0.7,
                text_threshold=0.7,
                low_text=0.4
            )

            all_coordinates = []
            individual_coords = []
            
            for line in result:
                bbox, text, confidence = line
                
                # Фильтр по уверенности
                if confidence < 0.5:
                    continue
                    
                logger.info(f"Распознано: '{text}' (уверенность: {confidence:.2f})")
                
                # Извлечение координат из текста
                coords = extractor.extract_all_coordinates(text, coord_status)
                
                # Если нашли 2 координаты в одном тексте - сразу возвращаем
                if len(coords) == 2:
                    coords[0] = coords[0].replace(",", ".")
                    coords[1] = coords[1].replace(",", ".")
                    return {img_link: coords}
                
                # Сохраняем одиночные координаты
                individual_coords.extend(coords)
                all_coordinates.extend(coords)
            
            # Удаление дубликатов из individual_coords
            unique_individual = []
            seen = set()
            for coord in individual_coords:
                if coord not in seen:
                    seen.add(coord)
                    unique_individual.append(coord)
            
            # Если нашли ровно 2 одиночные координаты - возвращаем их
            if len(unique_individual) == 2:
                ready_coords = []
                for coord in unique_individual:
                    ready_coords.append(coord.replace(",", "."))
                return {img_link: ready_coords}
            
            # Если нашли больше 2 координат - берем первые 2
            elif len(unique_individual) > 2:
                ready_coords = []
                for coord in unique_individual[:2]:
                    ready_coords.append(coord.replace(",", "."))
                return {img_link: ready_coords}

            return None
                
        except asyncio.TimeoutError:
            return f"Таймаут - {img_link}"
        except Exception as e:
            logger.error(f"Ошибка обработки {img_link}: {str(e)}")
            return f"Ошибка обработки - {img_link}: {str(e)}"


task_list = []


async def check_img(img_urls: list, coord_status: bool = False) -> list:
    """Улучшенный EasyOCR для поиска координат на фотографиях"""

    semaphore = asyncio.Semaphore(4)  # увеличить если нужно больше скорость
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