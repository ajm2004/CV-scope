"""Vehicle plate recognition.

    Vehicle detection (core tracker) -> Plate detection -> Plate crop
    -> Image preprocessing -> OCR -> Character confidence -> Temporal consensus
    -> Plate normalisation (format layer) -> Validation -> Plate event

Components: ``detector``, ``preprocessing``, ``ocr``, ``parser`` (configurable
country / region formats), ``temporal`` (multi-frame consensus). Characters
below the confidence floor are reported as '?', never invented.
"""
