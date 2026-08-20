"""Shared pandas Styler helpers for bold/colored top-N row highlighting."""
import pandas as pd
from pandas.io.formats.style import Styler

GREEN = "color: #1b5e20; font-weight: bold"
RED = "color: #b71c1c; font-weight: bold"


def highlight_top_n(df: pd.DataFrame, n: int, css: str) -> Styler:
    """Bold/color the first n rows (e.g. a list already sorted best-first or worst-first)."""

    def _row_style(row: pd.Series) -> list[str]:
        pos = df.index.get_loc(row.name)
        return [css] * len(row) if pos < n else [""] * len(row)

    return df.style.hide(axis="index").apply(_row_style, axis=1)


def highlight_best_and_worst(df: pd.DataFrame, n: int = 3) -> Styler:
    """Bold/color the first n rows green (best) and the last n rows red (worst)."""

    def _row_style(row: pd.Series) -> list[str]:
        pos = df.index.get_loc(row.name)
        if pos < n:
            return [GREEN] * len(row)
        if pos >= len(df) - n:
            return [RED] * len(row)
        return [""] * len(row)

    return df.style.hide(axis="index").apply(_row_style, axis=1)
