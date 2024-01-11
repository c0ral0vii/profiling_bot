from ocr.main import check_img
from .parsing import get_imgs


async def check_filesharing(text: str, user: int):
    '''Проверка является ли текст файлообменником'''

    img_urls = await get_imgs(url=text, user=user)

    result = check_img(img_urls=img_urls)

    create_html(coords=result, user=user)
    
    return


def create_html(coords: dict, user: int):
    coords = {url: coord for url, coord in coords.items() if len(coord) >= 2}

    html_one = '''<!DOCTYPE HTML>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
        <style>
        html, body {
            height: 100%;
            padding: 0;
            margin: 0;
        }
        #map {
            /* configure the size of the map */
            width: 100%;
            height: 100%;
        }
        .leaflet-tooltip {
            background: transparent;
            border: none;
            box-shadow: none;
        }
        </style>
    </head>
    <body>
        <div id="map"></div>
        <script>'''
    html_two = r'''
        // Получаем первый элемент из объекта coordinates
        var firstKey = Object.keys(coordinates)[0];
        var firstValue = coordinates[firstKey];
    
        function getDistance(coord1, coord2) {
                    var lat1 = coord1[0], lon1 = coord1[1];
                    var lat2 = coord2[0], lon2 = coord2[1];
                
                    var R = 6371e3; // радиус Земли в метрах
                    var φ1 = lat1 * Math.PI/180; // φ, λ в радианах
                    var φ2 = lat2 * Math.PI/180;
                    var Δφ = (lat2-lat1) * Math.PI/180;
                    var Δλ = (lon2-lon1) * Math.PI/180;
                
                    var a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
                            Math.cos(φ1) * Math.cos(φ2) *
                            Math.sin(Δλ/2) * Math.sin(Δλ/2);
                    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                
                    return R * c; // в метрах
                }
                
                // initialize Leaflet
                var map = L.map('map', {
                    center: firstValue,
                    zoom: 15
                });
                
                L.tileLayer('http://{s}.tile.osm.org/{z}/{x}/{y}.png', {
                    attribution: '© <a href="http://osm.org/copyright">OpenStreetMap</a> contributors'
                }).addTo(map);
                
                Object.entries(coordinates).forEach(([imageUrl, coord]) => {
                // Check if coordinates are numbers
                if (!isNaN(coord[0]) && !isNaN(coord[1])) {
                    var marker = L.marker(coord).addTo(map);
    
                    // Calculate the distance to the nearest marker
                    var minDistance = Infinity;
                    var closestCoord;
                    Object.values(coordinates).forEach(c => {
                        if (c !== coord && !isNaN(c[0]) && !isNaN(c[1])) {
                            var distance = getDistance(coord, c);
                            if (distance < minDistance) {
                                minDistance = distance;
                                closestCoord = c;
                            }
                        }
                    });
                    var tooltipContent = `<h7>${minDistance.toFixed(2)} м</h7>`;
    
                    var tooltipOptions = {
                        permanent: true, // tooltip is always visible
                        direction: "bottom", // tooltip will be to the right of the marker
                        offset: L.point(-15, 25) // offset of the tooltip relative to the marker
                    };
    
                    marker.bindTooltip(tooltipContent, tooltipOptions).openTooltip(); // Open the tooltip immediately
    
                    marker.on('click', function(e) {
                        // Add distance information to the popup
                        var popupContent = `<img src="${imageUrl}" alt="${coord[0]}, ${coord[1]}" width="300" height="400">
                        <a href='${imageUrl}'>Ссылка на фотографию</a>`;
                        var popup = L.popup().setContent(popupContent);
    
                        popup.setLatLng(e.latlng);
                        popup.openOn(map);
                    });
    
                    // Close the popup when clicking anywhere on the map
                    map.on('click', function() {
                        map.closePopup();
                    });
                }
            });
        </script>
    </body>
    </html>'''

    options = f'var coordinates = {coords};'
    gen_map = f'map/generate_map/{user}/leaflet.html'

    with open(gen_map, 'w', encoding='utf-8') as file:
        file.write(html_one + options + html_two)