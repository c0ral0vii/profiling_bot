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

class CoordinateExtractor:
    def __init__(self):
        self.reader = Reader(["en", "ru"], gpu=False)
        self.ssl_context = self._create_ssl_context()
        
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

    def _create_ssl_context(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

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
            
            # Конвертация в grayscale с улучшенной гаммой
            img = img.convert("L")
            img_array = np.array(img)
            
            # Гистограммная нормализация
            img_array = self._histogram_equalization(img_array)
            
            return img_array
        except Exception as e:
            logger.warning(f"Ошибка улучшения изображения: {e}")
            return np.array(img.convert("L"))

    def _histogram_equalization(self, img_array: np.ndarray) -> np.ndarray:
        """Выравнивание гистограммы для улучшения контраста"""
        # Простое выравнивание гистограммы
        hist, bins = np.histogram(img_array.flatten(), 256, [0,256])
        cdf = hist.cumsum()
        cdf_normalized = cdf * hist.max() / cdf.max()
        cdf_m = np.ma.masked_equal(cdf, 0)
        cdf_m = (cdf_m - cdf_m.min()) * 255 / (cdf_m.max() - cdf_m.min())
        cdf = np.ma.filled(cdf_m, 0).astype('uint8')
        return cdf[img_array]

    def is_plausible_coordinate(self, coord: str) -> bool:
        """Проверка, является ли строка правдоподобной координатой"""
        try:
            num = float(coord)
            
            # Более строгие проверки для координат
            if abs(num) > 180:  # Максимальные значения координат
                return False
                
            # Проверка на минимальную значимость (исключаем 0.0001 и подобные)
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

    def has_coordinate_context(self, text: str) -> bool:
        """Проверка контекста на наличие слов, связанных с координатами"""
        text_lower = text.lower()
        return any(word in text_lower for word in self.context_words)

    def extract_all_coordinates(self, text: str) -> List[str]:
        """Извлечение всех возможных координат из текста"""
        # Основные паттерны для координат
        patterns = [
            r'-?\d{1,3}\.\d{3,8}',  # 30.123456
            r'-?\d{1,3}\,\d{3,8}',  # 30,123456
            r'-?\d{1,3}\s\d{3,8}',  # 30 123456 (с пробелом)
        ]
        
        all_coords = []
        for pattern in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                coord = match.group()
                # Нормализация формата
                coord = coord.replace(',', '.').replace(' ', '')
                
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

    def group_coordinates(self, coordinates: List[str]) -> List[List[str]]:
        """Группировка координат в пары (широта, долгота)"""
        if len(coordinates) < 2:
            return []
            
        # Простая группировка по порядку
        pairs = []
        for i in range(0, len(coordinates) - 1, 2):
            pairs.append([coordinates[i], coordinates[i + 1]])
            
        return pairs

async def process_img(
    img_link: str,
    extractor: CoordinateExtractor,
    semaphore: asyncio.Semaphore,
    coord_status: bool = False,
) -> Union[Dict, str, None]:
    async with semaphore:
        try:
            if "%IMAGE_EXT%" in img_link:
                img_link = img_link.replace("%IMAGE_EXT%", "jpg")

            async with aiohttp.ClientSession() as session:
                async with session.get(img_link, ssl=extractor.ssl_context, timeout=30) as response:
                    if response.status == 200:
                        img_data = await response.read()
                    else:
                        return f"Ошибка загрузки - {img_link}"

            img = Image.open(BytesIO(img_data))
            img_processed = extractor.enhance_image_quality(img)
            
            # Распознавание текста
            result = extractor.reader.readtext(
                img_processed,
                detail=1,
                paragraph=False,
                contrast_ths=0.1,
                adjust_contrast=0.7,
                text_threshold=0.8,
                low_text=0.4,
                link_threshold=0.4
            )

            all_text = ""
            all_coordinates = []
            
            for line in result:
                bbox, text, confidence = line
                
                # Более строгий фильтр по уверенности
                if confidence < 0.6:
                    continue
                    
                logger.info(f"Распознано: '{text}' (уверенность: {confidence:.2f})")
                all_text += f" {text}"
                
                # Извлечение координат из текущего текста
                coords = extractor.extract_all_coordinates(text)
                all_coordinates.extend(coords)
            
            # Дополнительный поиск по всему объединенному тексту
            additional_coords = extractor.extract_all_coordinates(all_text)
            all_coordinates.extend(additional_coords)
            
            # Удаление дубликатов
            unique_coords = []
            seen = set()
            for coord in all_coordinates:
                if coord not in seen:
                    seen.add(coord)
                    unique_coords.append(coord)
            
            logger.info(f"Найдено координат для {img_link}: {unique_coords}")
            
            if unique_coords:
                # Группировка в пары
                coordinate_pairs = extractor.group_coordinates(unique_coords)
                
                result_data = {
                    "image_url": img_link,
                    "all_coordinates": unique_coords,
                    "coordinate_pairs": coordinate_pairs,
                    "coordinates_found": len(unique_coords),
                    "pairs_found": len(coordinate_pairs)
                }
                
                return result_data
            else:
                return None
                
        except asyncio.TimeoutError:
            return f"Таймаут - {img_link}"
        except Exception as e:
            logger.error(f"Ошибка обработки {img_link}: {str(e)}")
            return f"Ошибка обработки - {img_link}: {str(e)}"

# Глобальные переменные
extractor = CoordinateExtractor()
task_list = []

async def check_img(img_urls: List[str], coord_status: bool = False) -> List:
    """Улучшенный поиск координат на фотографиях"""
    
    semaphore = asyncio.Semaphore(4)
    tasks = [
        asyncio.create_task(process_img(img_link, extractor, semaphore, coord_status))
        for img_link in img_urls
    ]

    # Сохраняем задачи для возможной отмены
    task_list.extend(tasks)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful_results = []
    stats = {
        'total_images': len(img_urls),
        'processed_successfully': 0,
        'with_coordinates': 0,
        'total_coordinates_found': 0,
        'total_pairs_found': 0,
        'errors': 0
    }

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Ошибка: {result}")
            stats['errors'] += 1
        elif isinstance(result, dict):
            successful_results.append(result)
            stats['processed_successfully'] += 1
            stats['with_coordinates'] += 1
            stats['total_coordinates_found'] += result['coordinates_found']
            stats['total_pairs_found'] += result['pairs_found']
        elif isinstance(result, str) and result.startswith('Ошибка'):
            logger.error(result)
            stats['errors'] += 1
        else:
            stats['processed_successfully'] += 1

    # Очищаем список задач
    task_list.clear()

    return [
        successful_results,
        stats,
        f"Обработано: {stats['processed_successfully']}/{stats['total_images']}, "
        f"Координат: {stats['total_coordinates_found']}, "
        f"Пар: {stats['total_pairs_found']}"
    ]

async def stop() -> str:
    """Остановка обработки фотографий"""
    if task_list:
        for task in task_list:
            if not task.done():
                task.cancel()
        stopped_count = len(task_list)
        task_list.clear()
        return f"Остановлено {stopped_count} задач"
    else:
        return "Нет активных задач для остановки"