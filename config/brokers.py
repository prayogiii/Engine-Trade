"""Klasifikasi & metadata broker BEI/IDX."""

BROKER_TYPES: dict[str, str] = {
    "AK": "Foreign", "BK": "Foreign", "ZP": "Foreign", "RX": "Foreign",
    "YU": "Foreign", "KZ": "Foreign", "KK": "Foreign",
    "YP": "Foreign", "CP": "Foreign", "DU": "Foreign", "BQ": "Foreign",
    "HD": "Foreign", "DR": "Foreign", "TP": "Foreign", "AG": "Foreign",
    "XA": "Foreign", "AI": "Foreign", "FS": "Foreign", "LS": "Foreign",
    "DP": "Foreign", "RB": "Foreign", "AH": "Foreign", "GI": "Foreign",
    "CC": "BUMN", "NI": "BUMN", "OD": "BUMN", "DX": "BUMN",
    "XL": "Domestic", "LG": "Domestic", "PD": "Domestic", "SQ": "Domestic",
    "XC": "Domestic", "MG": "Domestic", "AZ": "Domestic", "GR": "Domestic",
    "DH": "Domestic", "YB": "Domestic", "EP": "Domestic", "FZ": "Domestic",
    "KI": "Domestic", "IF": "Domestic", "PP": "Domestic", "HP": "Domestic",
    "BB": "Domestic", "YJ": "Domestic", "AP": "Domestic", "CD": "Domestic",
    "PO": "Domestic", "AO": "Domestic", "BR": "Domestic", "SS": "Domestic",
    "AT": "Domestic", "IN": "Domestic", "RF": "Domestic", "EL": "Domestic",
    "RO": "Domestic", "SH": "Domestic", "PC": "Domestic", "PG": "Domestic",
    "II": "Domestic", "IH": "Domestic", "IU": "Domestic", "AR": "Domestic",
    "ES": "Domestic", "ZR": "Domestic", "MI": "Domestic", "PI": "Domestic",
    "SA": "Domestic", "MU": "Domestic", "SF": "Domestic", "QA": "Domestic",
    "ID": "Domestic", "RS": "Domestic", "RG": "Domestic", "GA": "Domestic",
    "AF": "Domestic", "TS": "Domestic", "PF": "Domestic", "BS": "Domestic",
    "AD": "Domestic", "TF": "Domestic", "OK": "Domestic", "JB": "Domestic",
    "IC": "Domestic", "BF": "Domestic", "IT": "Domestic", "DD": "Domestic",
    "YO": "Domestic", "FO": "Domestic",
}

RETAIL_BROKERS: set[str] = {
    "YP", "PD", "XL", "XC", "CC", "NI", "OD", "ID", "SQ",
    "KK", "DX", "AZ", "BK", "HP", "KS", "TF",
}

BANDAR_BROKERS: set[str] = {
    "AK", "KZ", "CS", "RX", "ZP", "YU", "DR", "CP", "HD",
    "AI", "LS", "BB", "TP", "DU", "FS", "DP",
}


def get_broker_label(code: str) -> str:
    """Format: 'XL (L)', 'CC (G)', 'AK (F)'."""
    cat = BROKER_TYPES.get(code, "Domestic")
    badge = "F" if cat == "Foreign" else ("G" if cat == "BUMN" else "L")
    return f"{code} ({badge})"