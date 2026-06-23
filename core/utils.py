import re


def normalize_pakistani_phone_number(value: str) -> str:
    val = value.strip().replace(" ", "")
    if re.match(r"^03\d{9}$", val):
        return f"{val[:4]}-{val[4:]}"
    if re.match(r"^\+923\d{9}$", val):
        return f"{val[:6]}-{val[6:]}"
    return val
