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

# Детальное логирование
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

pool_instance = None
reader = Reader(["en"], gpu=False)

class DebugCoordinateExtractor:
    def __init__(self):
        self.original_patterns = {
            False: r"([1-9]\d[.,]\d{4,6})",  # Оригинальный паттерн для coord_status=False
            True: r"([1-9]+[.,]\d{4,6})"     # Оригинальный паттерн для coord_status=True
        }
        
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
        """Улучшение качества изображения для лучшего распознавания"""
        try:
            # Увеличение резкости
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            
            # Увеличение контраста
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
            
            # Конвертация в grayscale
            img = img.convert("L")
            img_array = np.array(img)
            
            return img_array
        except Exception as e:
            logger.warning(f"Ошибка улучшения изображения: {e}")
            return np.array(img.convert("L"))

    def extract_coordinates_original(self, text: str, coord_status: bool = False) -> List[str]:
        """Оригинальный метод извлечения координат"""
        pattern = self.original_patterns[coord_status]
        coords = re.findall(pattern, text)
        logger.debug(f"ОРИГИНАЛЬНЫЙ МЕТОД: текст='{text}', паттерн='{pattern}', найдено={coords}")
        return coords

    def extract_coordinates_improved(self, text: str, coord_status: bool = False) -> List[str]:
        """Улучшенный метод извлечения координат"""
        if coord_status:
            patterns = [
                r'[1-9]+[.,]\d{4,8}',  # Оригинальный + расширенный
            ]
        else:
            patterns = [
                r'[1-9]\d[.,]\d{4,8}',  # Оригинальный + расширенный
            ]
        
        all_coords = []
        for pattern in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                coord = match.group()
                coord = coord.replace(',', '.')
                
                # Пропускаем явные ложные срабатывания
                if self.is_false_positive(text, coord):
                    logger.debug(f"Ложное срабатывание: '{coord}' в тексте '{text}'")
                    continue
                    
                all_coords.append(coord)
        
        logger.debug(f"УЛУЧШЕННЫЙ МЕТОД: текст='{text}', найдено={all_coords}")
        return all_coords

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
            
        return False

# Глобальный экземпляр экстрактора
debug_extractor = DebugCoordinateExtractor()

async def process_img(
    img_link: str,
    reader: Reader,
    semaphore: asyncio.Semaphore,
    coord_status: bool = False,
) -> dict | str | None:
    async with semaphore:
        try:
            logger.info(f"=== ОБРАБОТКА ИЗОБРАЖЕНИЯ: {img_link} ===")
            
            if "%IMAGE_EXT%" in img_link:
                img_link = img_link.replace("%IMAGE_EXT%", "jpg")

            async with aiohttp.ClientSession() as session:
                async with session.get(img_link, ssl=ctx) as response:
                    if response.status == 200:
                        img_data = await response.read()
                        logger.debug(f"Изображение загружено успешно, размер: {len(img_data)} байт")
                    else:
                        logger.error(f"Ошибка загрузки изображения: {response.status}")
                        return f"Ошибка - {img_link}"

            img = Image.open(BytesIO(img_data))
            img_processed = debug_extractor.enhance_image_quality(img)

            # Распознавание текста
            result = reader.readtext(img_processed)
            logger.info(f"Распознано текстовых блоков: {len(result)}")

            two_cords = []
            coordinates = {}
            
            # ТЕСТ: сравниваем оба метода
            all_original_coords = []
            all_improved_coords = []
            
            for i, line in enumerate(result):
                bbox, text, confidence = line
                logger.info(f"Блок {i}: '{text}' (уверенность: {confidence:.2f})")
                
                # ОРИГИНАЛЬНЫЙ МЕТОД
                original_coords = debug_extractor.extract_coordinates_original(text, coord_status)
                all_original_coords.extend(original_coords)
                
                # УЛУЧШЕННЫЙ МЕТОД  
                improved_coords = debug_extractor.extract_coordinates_improved(text, coord_status)
                all_improved_coords.extend(improved_coords)
                
                # Оригинальная логика обработки
                if len(original_coords) == 2:
                    original_coords[0] = original_coords[0].replace(",", ".")
                    original_coords[1] = original_coords[1].replace(",", ".")
                    coordinates[img_link] = original_coords
                    logger.info(f"ОРИГИНАЛЬНЫЙ МЕТОД НАШЕЛ 2 КООРДИНАТЫ: {original_coords}")
                    continue

                if len(original_coords) == 1 and len(original_coords) != 2:
                    two_cords.append(original_coords)
                    continue

            # Сравниваем результаты
            logger.info(f"=== РЕЗУЛЬТАТЫ ДЛЯ {img_link} ===")
            logger.info(f"Оригинальный метод: {all_original_coords}")
            logger.info(f"Улучшенный метод: {all_improved_coords}")
            logger.info(f"Two_cords: {two_cords}")
            
            # Оригинальная логика возврата
            if len(two_cords) == 2:
                ready_coords = []
                for cord_pair in two_cords:
                    if cord_pair:
                        ready_coords.append(cord_pair[0].replace(",", "."))
                if len(ready_coords) == 2:
                    logger.info(f"ВОЗВРАЩАЕМ КООРДИНАТЫ ИЗ TWO_CORDS: {ready_coords}")
                    return {img_link: ready_coords}

            if coordinates:
                logger.info(f"ВОЗВРАЩАЕМ КООРДИНАТЫ: {coordinates[img_link]}")
                return coordinates

            logger.info("КООРДИНАТЫ НЕ НАЙДЕНЫ")
            return None
                
        except asyncio.TimeoutError:
            logger.error(f"Таймаут при обработке {img_link}")
            return f"Таймаут - {img_link}"
        except Exception as e:
            logger.error(f"Ошибка обработки {img_link}: {str(e)}", exc_info=True)
            return f"Ошибка обработки - {img_link}: {str(e)}"


task_list = []


async def check_img(img_urls: list, coord_status: bool = False) -> list:
    """EasyOCR смотрит фотографию и ищет координаты на нём"""

    semaphore = asyncio.Semaphore(4)
    tasks = [
        asyncio.create_task(process_img(img_link, reader, semaphore, coord_status))
        for img_link in img_urls
    ]

    for task in tasks:
        task_list.append(task)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    coordinates = {}
    stats = {
        'total': len(img_urls),
        'success': 0,
        'errors': 0,
        'with_coords': 0
    }

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Ошибка: {result}")
            stats['errors'] += 1
        elif isinstance(result, dict):
            coordinates.update(result)
            stats['success'] += 1
            stats['with_coords'] += 1
            logger.info(f"Успешно обработан с координатами: {list(result.keys())[0]}")
        elif isinstance(result, str) and result.startswith('Ошибка'):
            logger.error(f"Ошибка обработки: {result}")
            stats['errors'] += 1
        else:
            stats['success'] += 1
            logger.info("Обработан без координат")

    logger.info(f"=== ИТОГОВАЯ СТАТИСТИКА ===")
    logger.info(f"Обработано: {stats['success']}/{stats['total']}")
    logger.info(f"С координатами: {stats['with_coords']}")
    logger.info(f"Ошибок: {stats['errors']}")

    return [coordinates, f"{len(coordinates)}/{len(img_urls)}"]


async def stop() -> str:
    """Остановка обработки фотографий"""
    if len(task_list) > 0:
        for task in task_list:
            task.cancel()
        return "Остановлено"
    else:
        return "Никаких задач сейчас нет"