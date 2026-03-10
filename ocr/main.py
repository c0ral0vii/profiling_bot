import asyncio
import logging
import os
import re
import ssl
from io import BytesIO
from typing import List

import aiohttp
import numpy as np
from PIL import Image, ImageEnhance

# Настройки должны быть выставлены до импорта PaddleOCR/PaddleX.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault(
    "PADDLE_PDX_CACHE_HOME",
    os.path.join(os.getcwd(), ".paddlex-cache"),
)
os.environ.setdefault("FLAGS_use_mkldnn", "0")

from paddleocr import PaddleOCR

# Детальное логирование
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

ssl._create_default_https_context = ssl._create_unverified_context

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Инициализация PaddleOCR PP-OCRv5 (глобальный экземпляр)
# приводит к падению вида ConvertPirAttribute2RuntimeAttribute/oneDNN.
ocr_kwargs = {
    "text_detection_model_name": "PP-OCRv5_mobile_det",
    "text_recognition_model_name": "PP-OCRv5_mobile_rec",
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    "use_textline_orientation": False,
    "text_rec_score_thresh": 0.0,
}
safe_runtime_kwargs = {
    "device": "cpu",
    "enable_hpi": False,
    "enable_mkldnn": False,
    "enable_cinn": False,
    "cpu_threads": 4,
}

try:
    ocr = PaddleOCR(**ocr_kwargs, **safe_runtime_kwargs)
except TypeError:
    # Совместимость со старыми версиями, где runtime-флаги отсутствуют.
    ocr = PaddleOCR(**ocr_kwargs)

pool_instance = None


class DebugCoordinateExtractor:
    def __init__(self):
        self.original_patterns = {
            False: r"([1-9]\d[.,]\d{4,6})",  # Оригинальный паттерн для coord_status=False
            True: r"([1-9]+[.,]\d{4,6})",  # Оригинальный паттерн для coord_status=True
        }

        # Черный список для фильтрации ложных срабатываний
        self.blacklist_patterns = [
            r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",  # Даты
            r"\d+\.\d+\+-\d+\.\d+",  # Погрешности 447.86+-3.00
            r"\d+\.\d+[мm]",  # Метры 10.24м
            r"v?\d+\.\d+\.\d+",  # Версии ПО v1.2.3
            r"\d+\.\d+%",  # Проценты
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",  # IP-адреса
        ]

    def normalize_text_for_coords(self, text: str) -> str:
        """Нормализация OCR-артефактов в числах координат."""
        # OCR часто путает десятичную точку с ':' или ';' (например 55:814349).
        text = re.sub(r"(?<=\d)[:;](?=\d)", ".", text)
        # Встречаются нестандартные разделители между двумя координатами.
        text = text.replace("±", ",")
        text = re.sub(r"(?<=\d)\s*[/|]\s*(?=[+\-]?\d)", ",", text)
        # Склейка разрыва внутри координаты: "+55 768095" -> "+55768095".
        text = re.sub(r"([+\-]\d{1,2})\s+(\d{4,10})", r"\1\2", text)
        return text

    def _repair_compact_coordinate_token(
        self, token: str, coord_status: bool = False
    ) -> str | None:
        """
        Восстанавливает координату из слитного числового токена без точки:
        37242142 -> 37.242142, 551769182 -> 55.1769182.
        """
        sign = "-" if token.startswith("-") else ""
        digits = re.sub(r"\D", "", token)

        if len(digits) < 7:
            return None

        # Частая ошибка OCR: лишняя первая цифра перед широтой (455767579 -> 55.767579).
        if len(digits) >= 9 and digits[0] in {"3", "4"}:
            try:
                repaired_head = int(digits[1:3])
                if 50 <= repaired_head <= 89:
                    digits = digits[1:]
            except ValueError:
                pass

        preferred_degree_len = 1 if coord_status else 2
        for degree_len in (preferred_degree_len, 2, 3):
            if len(digits) - degree_len < 4:
                continue

            int_part = digits[:degree_len]
            frac_part = digits[degree_len:]

            if len(frac_part) > 8:
                frac_part = frac_part[:8]
            if len(frac_part) < 4:
                continue

            candidate = f"{int_part}.{frac_part}"
            try:
                value = float(candidate)
            except ValueError:
                continue

            if 0 < value <= 180:
                return f"{sign}{candidate}"

        return None

    def enhance_image_quality(self, img: Image.Image) -> np.ndarray:
        """Улучшение качества изображения для лучшего распознавания"""
        try:
            # Увеличение резкости
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)

            # Увеличение контраста
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)

            # Конвертация в RGB (PaddleOCR требует 3 канала)
            img = img.convert("RGB")
            img_array = np.array(img)

            return img_array
        except Exception as e:
            logger.warning(f"Ошибка улучшения изображения: {e}")
            return np.array(img.convert("RGB"))

    def extract_coordinates_original(
        self, text: str, coord_status: bool = False
    ) -> List[str]:
        """Оригинальный метод извлечения координат"""
        pattern = self.original_patterns[coord_status]
        normalized_text = self.normalize_text_for_coords(text)
        coords = re.findall(pattern, normalized_text)
        logger.debug(
            f"ОРИГИНАЛЬНЫЙ МЕТОД: текст='{text}', normalized='{normalized_text}', паттерн='{pattern}', найдено={coords}"
        )
        return coords

    def extract_coordinates_improved(
        self, text: str, coord_status: bool = False
    ) -> List[str]:
        """Улучшенный метод извлечения координат"""
        normalized_text = self.normalize_text_for_coords(text)

        if coord_status:
            patterns = [
                r"[1-9]+[.,]\d{4,8}",  # Оригинальный + расширенный
            ]
        else:
            patterns = [
                r"[1-9]\d[.,]\d{4,8}",  # Оригинальный + расширенный
            ]

        ordered_candidates = []
        for pattern in patterns:
            matches = re.finditer(pattern, normalized_text)
            for match in matches:
                coord = match.group()
                coord = coord.replace(",", ".")

                # Пропускаем явные ложные срабатывания
                if self.is_false_positive(normalized_text, coord):
                    logger.debug(f"Ложное срабатывание: '{coord}' в тексте '{text}'")
                    continue

                ordered_candidates.append((match.start(), coord))

        # Фолбэк для случаев, где OCR "съел" десятичную точку в одной из координат.
        compact_matches = re.finditer(r"[+\-]?\d{7,10}", normalized_text)
        for match in compact_matches:
            token = match.group()
            repaired = self._repair_compact_coordinate_token(token, coord_status)
            if not repaired:
                continue
            if self.is_false_positive(normalized_text, repaired):
                continue
            ordered_candidates.append((match.start(), repaired))

        # Сохраняем естественный порядок координат в исходной строке.
        ordered_candidates.sort(key=lambda item: item[0])

        all_coords = []
        seen = set()
        for _, coord in ordered_candidates:
            if coord in seen:
                continue
            seen.add(coord)
            all_coords.append(coord)

        # На некоторых OCR-шумах из одного фрагмента может получиться >2 кандидатов.
        # Берем первые по позиции в исходной строке.
        if len(all_coords) > 2:
            all_coords = all_coords[:2]

        logger.debug(
            f"УЛУЧШЕННЫЙ МЕТОД: текст='{text}', normalized='{normalized_text}', найдено={all_coords}"
        )
        return all_coords

    def is_false_positive(self, text: str, coord: str) -> bool:
        """Проверка на ложное срабатывание"""
        text_lower = text.lower()

        # Проверка по черному списку паттернов
        for pattern in self.blacklist_patterns:
            if re.search(pattern, text_lower):
                return True

        # Специфичные проверки для координат
        if re.match(r"^\d{1,2}\.\d{1,2}$", coord):  # 10.24 - вероятно не координата
            return True

        return False


# Глобальный экземпляр экстрактора
debug_extractor = DebugCoordinateExtractor()


def _extract_ocr_results(raw_result) -> List[tuple]:
    """Нормализация результатов OCR для PaddleOCR 2.x/3.x."""
    normalized = []

    def first_not_none(*values):
        for value in values:
            if value is not None:
                return value
        return []

    if raw_result is None:
        return normalized

    for res in raw_result:
        rec_texts = None
        rec_scores = None
        rec_boxes = None

        # PaddleOCR 3.x (BaseResult, наследник dict)
        if isinstance(res, dict):
            rec_texts = first_not_none(res.get("rec_texts"), [])
            rec_scores = first_not_none(res.get("rec_scores"), [])
            rec_boxes = first_not_none(res.get("rec_boxes"), res.get("rec_polys"), [])

        # Объектный формат (на случай отличий между версиями)
        elif hasattr(res, "rec_texts"):
            rec_texts = first_not_none(getattr(res, "rec_texts", None), [])
            rec_scores = first_not_none(getattr(res, "rec_scores", None), [])
            rec_boxes = first_not_none(getattr(res, "rec_boxes", None), [])

        # Legacy-формат PaddleOCR 2.x: [[box, (text, score)], ...]
        elif isinstance(res, list):
            for item in res:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                bbox = item[0]
                value = item[1]
                if isinstance(value, (list, tuple)) and len(value) >= 2:
                    text = str(value[0])
                    score = float(value[1])
                else:
                    text = str(value)
                    score = 0.0
                normalized.append((bbox, text, score))
            continue

        else:
            continue

        for i, text in enumerate(rec_texts):
            score = float(rec_scores[i]) if i < len(rec_scores) else 0.0
            bbox = rec_boxes[i] if i < len(rec_boxes) else None
            normalized.append((bbox, str(text), score))

    return normalized


def _describe_ocr_raw_result(raw_result) -> str:
    """Короткая диагностика формата сырых OCR результатов."""
    if raw_result is None:
        return "raw_result=None"

    try:
        total = len(raw_result)
    except TypeError:
        return f"raw_result_type={type(raw_result).__name__}"

    if total == 0:
        return "raw_result=[]"

    first = raw_result[0]
    if isinstance(first, dict):
        keys = list(first.keys())
        rec_count = len(first.get("rec_texts") or [])
        return f"items={total}, first_type=dict, keys={keys}, rec_texts={rec_count}"

    return f"items={total}, first_type={type(first).__name__}"


async def process_img(
    img_link: str,
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
                        logger.debug(
                            f"Изображение загружено успешно, размер: {len(img_data)} байт"
                        )
                    else:
                        logger.error(f"Ошибка загрузки изображения: {response.status}")
                        return f"Ошибка - {img_link}"

            img = Image.open(BytesIO(img_data))
            img_processed = debug_extractor.enhance_image_quality(img)

            # Распознавание текста через PaddleOCR PP-OCRv5.
            # Для скриншотов с мелким текстом делаем более чувствительный проход.
            result = ocr.predict(
                img_processed,
                text_det_limit_side_len=1536,
                text_det_limit_type="max",
                text_det_thresh=0.2,
                text_det_box_thresh=0.3,
                text_rec_score_thresh=0.0,
            )
            ocr_results = _extract_ocr_results(result)
            if not ocr_results:
                logger.debug(
                    f"OCR проход #1 пустой: {_describe_ocr_raw_result(result)}"
                )

            if not ocr_results:
                # Повторный проход на увеличенном изображении для мелкого текста.
                h, w = img_processed.shape[:2]
                upscaled = np.array(
                    Image.fromarray(img_processed).resize(
                        (w * 2, h * 2), Image.Resampling.LANCZOS
                    )
                )
                result = ocr.predict(
                    upscaled,
                    text_det_limit_side_len=2048,
                    text_det_limit_type="max",
                    text_det_thresh=0.2,
                    text_det_box_thresh=0.3,
                    text_rec_score_thresh=0.0,
                )
                ocr_results = _extract_ocr_results(result)
                if not ocr_results:
                    logger.debug(
                        f"OCR проход #2 (upscale) пустой: {_describe_ocr_raw_result(result)}"
                    )

            if not ocr_results:
                # Фолбэк: пробуем оригинал без усиления, если препроцессинг "пережал" картинку.
                original_rgb = np.array(img.convert("RGB"))
                result = ocr.predict(
                    original_rgb,
                    text_det_limit_side_len=1536,
                    text_det_limit_type="max",
                    text_det_thresh=0.2,
                    text_det_box_thresh=0.3,
                    text_rec_score_thresh=0.0,
                )
                ocr_results = _extract_ocr_results(result)
                if not ocr_results:
                    logger.debug(
                        f"OCR проход #3 (original) пустой: {_describe_ocr_raw_result(result)}"
                    )

            logger.info(f"Распознано текстовых блоков: {len(ocr_results)}")

            two_cords = []
            coordinates = {}

            # ТЕСТ: сравниваем оба метода
            all_original_coords = []
            all_improved_coords = []

            for i, line in enumerate(ocr_results):
                bbox, text, confidence = line
                logger.info(f"Блок {i}: '{text}' (уверенность: {confidence:.2f})")

                text_variants = [text]
                if i + 1 < len(ocr_results):
                    next_text = str(ocr_results[i + 1][1]).strip()
                    if re.fullmatch(r"[+\-]?\d{1,2}", str(text).strip()) and re.match(
                        r"\d{4,10}", next_text
                    ):
                        merged_text = f"{str(text).strip()}{next_text}"
                        text_variants.append(merged_text)
                        logger.debug(
                            f"СКЛЕЙКА БЛОКОВ: '{text}' + '{next_text}' -> '{merged_text}'"
                        )

                original_coords = []
                improved_coords = []
                for text_variant in text_variants:
                    # ОРИГИНАЛЬНЫЙ МЕТОД
                    original_variant = debug_extractor.extract_coordinates_original(
                        text_variant, coord_status
                    )
                    original_coords.extend(original_variant)

                    # УЛУЧШЕННЫЙ МЕТОД
                    improved_variant = debug_extractor.extract_coordinates_improved(
                        text_variant, coord_status
                    )
                    improved_coords.extend(improved_variant)

                original_coords = list(dict.fromkeys(original_coords))
                improved_coords = list(dict.fromkeys(improved_coords))
                all_original_coords.extend(original_coords)
                all_improved_coords.extend(improved_coords)

                # Оригинальная логика обработки
                if len(original_coords) == 2:
                    original_coords[0] = original_coords[0].replace(",", ".")
                    original_coords[1] = original_coords[1].replace(",", ".")
                    coordinates[img_link] = original_coords
                    logger.info(
                        f"ОРИГИНАЛЬНЫЙ МЕТОД НАШЕЛ 2 КООРДИНАТЫ: {original_coords}"
                    )
                    continue

                # Фолбэк: если оригинальный regex не нашел пару, используем расширенный.
                if len(improved_coords) == 2:
                    improved_coords[0] = improved_coords[0].replace(",", ".")
                    improved_coords[1] = improved_coords[1].replace(",", ".")
                    coordinates[img_link] = improved_coords
                    logger.info(
                        f"УЛУЧШЕННЫЙ МЕТОД НАШЕЛ 2 КООРДИНАТЫ: {improved_coords}"
                    )
                    continue

                if len(original_coords) == 1:
                    two_cords.append(original_coords)
                    continue

                if len(improved_coords) == 1:
                    two_cords.append(improved_coords)
                    continue

            # Сравниваем результаты
            logger.info(f"=== РЕЗУЛЬТАТЫ ДЛЯ {img_link} ===")
            logger.info(f"Оригинальный метод: {all_original_coords}")
            logger.info(f"Улучшенный метод: {all_improved_coords}")
            logger.info(f"Two_cords: {two_cords}")

            if coordinates:
                logger.info(f"ВОЗВРАЩАЕМ КООРДИНАТЫ: {coordinates[img_link]}")
                return coordinates

            # Оригинальная логика возврата (фолбэк, если полная пара не была найдена)
            if len(two_cords) == 2:
                ready_coords = []
                for cord_pair in two_cords:
                    if cord_pair:
                        ready_coords.append(cord_pair[0].replace(",", "."))
                if len(ready_coords) == 2:
                    logger.info(f"ВОЗВРАЩАЕМ КООРДИНАТЫ ИЗ TWO_CORDS: {ready_coords}")
                    return {img_link: ready_coords}

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
    """PaddleOCR PP-OCRv5 смотрит фотографию и ищет координаты на нём"""

    semaphore = asyncio.Semaphore(2)
    tasks = [
        asyncio.create_task(process_img(img_link, semaphore, coord_status))
        for img_link in img_urls
    ]

    for task in tasks:
        task_list.append(task)
    results = await asyncio.gather(*tasks, return_exceptions=True)

    coordinates = {}
    stats = {"total": len(img_urls), "success": 0, "errors": 0, "with_coords": 0}

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"Ошибка: {result}")
            stats["errors"] += 1
        elif isinstance(result, dict):
            coordinates.update(result)
            stats["success"] += 1
            stats["with_coords"] += 1
            logger.info(f"Успешно обработан с координатами: {list(result.keys())[0]}")
        elif isinstance(result, str) and result.startswith("Ошибка"):
            logger.error(f"Ошибка обработки: {result}")
            stats["errors"] += 1
        else:
            stats["success"] += 1
            logger.info("Обработан без координат")

    logger.info("=== ИТОГОВАЯ СТАТИСТИКА ===")
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
