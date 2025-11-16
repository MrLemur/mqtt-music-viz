"""Colour palette helpers and conversion utilities."""
import random
from typing import Dict

COLOUR_PALETTE = [
    {"colour": "dark red", "value": "174,0,0"},
    {"colour": "red", "value": "255,0,0"},
    {"colour": "orange-red", "value": "255,102,0"},
    {"colour": "yellow", "value": "255,239,0"},
    {"colour": "chartreuse", "value": "153,255,0"},
    {"colour": "lime", "value": "40,255,0"},
    {"colour": "aqua", "value": "0,255,242"},
    {"colour": "sky blue", "value": "0,122,255"},
    {"colour": "blue", "value": "5,0,255"},
    {"colour": "blue", "value": "71,0,237"},
    {"colour": "indigo", "value": "99,0,178"},
]


def random_colour(exclude_value: str | None = None) -> Dict[str, str]:
    """Return random colour from palette, optionally excluding one by RGB value.
    
    Args:
        exclude_value: RGB string value to exclude (e.g., '255,0,0')
    
    Returns:
        Dict with 'name', 'rgb', 'hex', and 'value' keys
    """
    candidates = [c for c in COLOUR_PALETTE if c["value"] != exclude_value]
    chosen = random.choice(candidates) if candidates else COLOUR_PALETTE[0]
    return {
        'name': chosen['colour'],
        'rgb': chosen['value'],
        'hex': rgb_to_hex(chosen['value']),
        'value': chosen['value']  # for backwards compatibility
    }


def rgb_to_hex(rgb: str) -> str:
    """Convert RGB comma-separated string to hexadecimal colour code.
    
    Args:
        rgb: RGB string in format 'R,G,B' (e.g., '255,0,0')
    
    Returns:
        Hex colour string with # prefix (e.g., '#ff0000')
    """
    parts = [int(p) for p in rgb.split(",")]
    return "#" + "".join(f"{p:02x}" for p in parts)


def hex_to_rgb(hexstr: str) -> str:
    """Convert hexadecimal colour code to RGB comma-separated string.
    
    Args:
        hexstr: Hex colour string with or without # prefix (e.g., '#ff0000')
    
    Returns:
        RGB string in format 'R,G,B' (e.g., '255,0,0')
    """
    h = hexstr.lstrip("#")
    return ",".join(str(int(h[i : i + 2], 16)) for i in (0, 2, 4))
