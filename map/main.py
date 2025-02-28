import aiofiles


async def create_html(coords: dict, user: int):
    coords = {url: coord for url, coord in coords.items() if len(coord) >= 2}

    html_one = """<!DOCTYPE HTML>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://unpkg.com/@turf/turf@6.5.0/turf.min.js"></script>
    <style>
        html, body {
            height: 100%;
            padding: 0;
            margin: 0;
        }
        #map {
            width: 100%;
            height: 100%;
        }
        .leaflet-tooltip {
            background: transparent;
            border: none;
            box-shadow: none;
        }
        .leaflet-popup-content-wrapper {
        width: 120%;
        }

        .leaflet-popup-content-wrapper .popup-images div {
            margin: 5px;
        }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>"""
    html_two = r"""
        const markerGroups = [];

        // Проверяем, существует ли группа маркеров, где расстояние <= 100 метров
        function findGroup(coord, threshold = 0) {
            const point = turf.point([coord.lon, coord.lat]);

            for (const group of markerGroups) {
                const groupPoint = turf.point([group.lon, group.lat]);
                const distance = turf.distance(point, groupPoint, { units: 'meters' });

                if (distance <= threshold) {
                    return group;
                }
            }
            return null;
        }

        // Обработка координат
        Object.entries(coordinates).forEach(([imageUrl, coord]) => {
            const [lat, lon] = coord.slice(0, 2).map(c => parseFloat(c.replace(',', '.')));
            if (isNaN(lat) || isNaN(lon)) return;

            const existingGroup = findGroup({ lat, lon });

            if (existingGroup) {
                // Добавляем фото в правильную группу
                existingGroup.images.push(imageUrl);
                existingGroup.duplicates += 1;
            } else {
                // Создаем новую группу
                markerGroups.push({
                    lat,
                    lon,
                    images: [imageUrl],
                    duplicates: 1
                });
            }
        });

        // Инициализация карты
        const map = L.map('map', {
            center: markerGroups.length > 0 
                ? [markerGroups[0].lat, markerGroups[0].lon] 
                : [55.5803, 37.6657],
            zoom: 15
        });

        L.tileLayer('http://{s}.google.com/vt/lyrs=s,h&x={x}&y={y}&z={z}', {
            maxZoom: 22,
            subdomains: ['mt0', 'mt1', 'mt2', 'mt3']
        }).addTo(map);

        let markerCount = 0;
        let duplicateCount = 0;

        // Добавление маркеров на карту
        markerGroups.forEach((group) => {
            const { lat, lon, images, duplicates } = group;

            const marker = L.marker([lat, lon]).addTo(map);
            markerCount++;
            duplicateCount += duplicates - 1; // Учитываем только дополнительные дубли

            // Найти ближайший маркер
            let minDistance = Infinity;

            markerGroups.forEach((otherGroup) => {
                if (group !== otherGroup) {
                    const from = turf.point([lon, lat]);
                    const to = turf.point([otherGroup.lon, otherGroup.lat]);
                    const distance = turf.distance(from, to, { units: 'meters' });

                    if (distance < minDistance) {
                        minDistance = distance;
                    }
                }
            });

            // Создаем контент для всех фото в группе
            const popupContent = `
            <h5>Фотографий в группе: ${images.length}</h5>
            <div class="popup-images" style="display: flex">
                ${images.map(imageUrl => `
                    <div style="margin: 5px;">
                        <img src="${imageUrl}" alt="Image" width="140" height="180">
                        <a href="${imageUrl}">Ссылка на фотографию</a>
                    </div>
                `).join('')}
            </div>
        `;

            var tooltipContent = `
                <h7 style="color: yellow; font-size: 15px">${minDistance.toFixed(2)} м</h7>
            `;
            if (duplicates > 1) {
    tooltipContent += `
        <h7 style="color: red; font-size: 13px">Дубли: ${duplicates}</h7>
    `;
}
            
            const tooltipOptions = {
                permanent: true,
                direction: "bottom",
                offset: L.point(-15, 25)
            };

            marker.bindTooltip(tooltipContent, tooltipOptions).openTooltip();
            marker.bindPopup(popupContent);
        });

        // Показать количество маркеров
        const info = L.control();
        info.onAdd = function () {
            this._div = L.DomUtil.create('div', 'info');
            this.update();
            return this._div;
        };
        info.update = function () {
            this._div.innerHTML = `
                <h4 style="color: yellowgreen; font-size: 15px">
                    Число маркеров на карте: ${markerCount} (${duplicateCount} дублей)
                </h4>
            `;
        };
        info.addTo(map);
    </script>
</body>
</html>"""

    options = f"var coordinates = {coords};"
    gen_map = f"map/generate_map/{user}/leaflet.html"

    async with aiofiles.open(gen_map, "w", encoding="utf-8") as file:
        await file.write(html_one + options + html_two)
