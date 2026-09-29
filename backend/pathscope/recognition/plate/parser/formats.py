"""Built-in plate formats. Regional formats are deliberately simple and
explicit; add or override them with ``<data>/recognition/plate_formats.json``."""

from __future__ import annotations

from pathscope.recognition.plate.parser.base import PlateFormat

BUILTIN_FORMATS: list[PlateFormat] = [
    PlateFormat(
        id="generic", name="Generic (letters and digits)", country="", pattern=r"^(?P<number>[A-Z0-9]{2,10})$",
        description="Accepts any 2 to 10 letters or digits. Use it last as a fallback.", builtin=True,
    ),
    PlateFormat(
        id="uae", name="United Arab Emirates", country="AE",
        pattern=r"^(?P<emirate>DXB|AUH|SHJ|AJM|RAK|FUJ|UAQ)?(?P<category>[A-Z]{1,2})?(?P<number>[0-9]{1,5})$",
        description="Optional emirate code (DXB, AUH, SHJ, AJM, RAK, FUJ, UAQ), optional plate category letters, 1 to 5 digits.", builtin=True,
    ),
    PlateFormat(
        id="uk", name="United Kingdom (current style)", country="GB",
        pattern=r"^(?P<area>[A-Z]{2})(?P<age>[0-9]{2})(?P<random>[A-Z]{3})$",
        description="Two area letters, two age digits, three letters, for example AB12CDE.", builtin=True,
    ),
    PlateFormat(
        id="eu_generic", name="Europe (generic)", country="",
        pattern=r"^(?P<prefix>[A-Z]{1,3})(?P<series>[A-Z]{0,2})(?P<number>[0-9]{1,4})(?P<suffix>[A-Z]{0,2})$",
        description="One to three district letters, optional series letters, one to four digits, optional suffix letters.", builtin=True,
    ),
    PlateFormat(
        id="us_generic", name="United States (generic)", country="US",
        pattern=r"^(?P<number>[A-Z0-9]{5,8})$",
        description="Five to eight letters or digits; the state comes from the default region setting.", builtin=True,
    ),
]

BUILTIN_BY_ID: dict[str, PlateFormat] = {f.id: f for f in BUILTIN_FORMATS}
