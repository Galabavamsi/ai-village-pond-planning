"""Curated example study areas for the planner's place picker.

These are only convenient starting extents with real, varied terrain. They are
never used by the analysis itself; every algorithm input comes from the
selected polygon and the chosen elevation source. Each box was checked end to
end on 27 September 2026 (GLO-30 relief, CHIRPS monsoon total, Overpass
screening, three ranked sites). Distances are approximate, from the IIT Bhilai
campus (81.318 E, 21.245 N). Land-cover notes are from ESA WorldCover 2021.
"""

EXAMPLE_AREAS: list[dict] = [
    {
        "id": "khapri-sample",
        "name": "Khapri, beside IIT Bhilai (supplied contours)",
        "region": "Durg · Chhattisgarh · just west of campus",
        "source": "sample",
        "bbox": None,
        "note": "The supplied contour map: farmland between the campus and the Shivnath river (267–298 m).",
    },
    {
        "id": "dongargarh-khairagarh",
        "name": "Dongargarh–Khairagarh ridge",
        "region": "Rajnandgaon / Khairagarh · Chhattisgarh · ~48 km W",
        "source": "copernicus",
        "bbox": [80.8372, 21.2744, 80.8758, 21.3106],
        "note": "Closest real relief to the campus: a forested ridge above cropland with village clusters and tanks (about 290 m of relief).",
    },
    {
        "id": "maikal-ridge-front",
        "name": "Maikal ridge front",
        "region": "Kabirdham · Chhattisgarh · ~90 km N",
        "source": "copernicus",
        "bbox": [81.1444, 22.0194, 81.1833, 22.0556],
        "note": "Sharp ridge-to-plain edge south of Bhoramdeo; mostly cropland below the hills (about 390 m of relief).",
    },
    {
        "id": "kanker-west",
        "name": "Kanker west",
        "region": "Uttar Bastar Kanker · Chhattisgarh · ~110 km S",
        "source": "copernicus",
        "bbox": [81.4178, 20.2506, 81.4561, 20.2867],
        "note": "Rocky inselberg with surrounding tanks and villages such as Malgaon and Kokpur (about 290 m of relief).",
    },
    {
        "id": "sihawa-mahanadi",
        "name": "Sihawa, Mahanadi source",
        "region": "Dhamtari · Chhattisgarh · ~120 km SE",
        "source": "copernicus",
        "bbox": [81.900, 20.295, 81.930, 20.325],
        "note": "Undulating uplands where the Mahanadi rises; gentle terrain traced at 5 m contours.",
    },
    {
        "id": "mainpat-plateau",
        "name": "Mainpat plateau",
        "region": "Surguja · Chhattisgarh · ~265 km NE",
        "source": "copernicus",
        "bbox": [83.285, 22.785, 83.315, 22.815],
        "note": "Plateau top above 1,000 m; a very wet 2025 monsoon (about 1,600 mm).",
    },
    {
        "id": "ralegan-siddhi",
        "name": "Ralegan Siddhi watershed",
        "region": "Ahmednagar · Maharashtra",
        "source": "copernicus",
        "bbox": [74.395, 18.898, 74.425, 18.928],
        "note": "Well-known village watershed programme in a drought-prone, low-rainfall landscape.",
    },
    {
        "id": "hiware-bazar",
        "name": "Hiware Bazar",
        "region": "Ahmednagar · Maharashtra",
        "source": "copernicus",
        "bbox": [74.586, 19.053, 74.616, 19.083],
        "note": "Village known for community water harvesting on semi-arid hill slopes.",
    },
    {
        "id": "alwar-johads",
        "name": "Bheekampura johad country",
        "region": "Alwar · Rajasthan",
        "source": "copernicus",
        "bbox": [76.278, 27.249, 76.308, 27.279],
        "note": "Aravalli foothills where Tarun Bharat Sangh revived traditional johad ponds.",
    },
    {
        "id": "sukhomajri",
        "name": "Sukhomajri",
        "region": "Panchkula · Haryana",
        "source": "copernicus",
        "bbox": [76.865, 30.797, 76.901, 30.832],
        "note": "Shivalik foothill village often cited as a pioneer of participatory watershed management.",
    },
    {
        "id": "abreha-we-atsbeha",
        "name": "Abreha we Atsbeha",
        "region": "Tigray · Ethiopia",
        "source": "copernicus",
        "bbox": [39.515, 13.828, 39.555, 13.868],
        "note": "Highland village known for community watershed restoration; shows the planner outside India (1,900–2,500 m).",
    },
]
