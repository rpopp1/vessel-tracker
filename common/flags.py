from __future__ import annotations

# Maritime Identification Digits for the major tanker flags. Extend as needed.
_FLAGS = {
    "Panama": [351, 352, 353, 354, 355, 356, 357, 370, 371, 372, 373, 374],
    "Liberia": [636, 637],
    "Marshall Islands": [538],
    "Singapore": [563, 564, 565, 566],
    "Malta": [215, 229, 248, 249, 256],
    "Hong Kong": [477],
    "Greece": [237, 239, 240, 241],
    "Bahamas": [308, 309, 311],
    "Cyprus": [209, 210, 212],
    "Norway": [257, 258, 259],
    "United Kingdom": [232, 233, 234, 235],
    "United States": [338, 366, 367, 368, 369],
    "China": [412, 413, 414],
    "India": [419],
    "Japan": [431, 432],
    "South Korea": [440, 441],
    "Russia": [273],
    "Denmark": [219, 220],
    "Germany": [211, 218],
    "Netherlands": [244, 245, 246],
    "Italy": [247],
    "France": [226, 227, 228],
    "Turkey": [271],
    "Saudi Arabia": [403],
    "United Arab Emirates": [470, 471],
    "Indonesia": [525],
    "Malaysia": [533],
    "Gibraltar": [236],
    "Isle of Man": [],
}
_MID = {mid: name for name, mids in _FLAGS.items() for mid in mids}


def flag_from_mmsi(mmsi: int) -> str:
    s = str(mmsi)
    if len(s) != 9:
        return "Other"
    return _MID.get(int(s[:3]), "Other")
