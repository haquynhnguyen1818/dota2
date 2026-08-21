"""Shared pandas Styler helpers for bold/colored top-N row highlighting."""
import pandas as pd
from pandas.io.formats.style import Styler

GREEN = "color: #1b5e20; font-weight: bold"
RED = "color: #b71c1c; font-weight: bold"
WR_GREEN = "color: #1b5e20"
SUB_ROW_CSS = "color: #757575; font-style: italic"


def style_expandable_table(
    df: pd.DataFrame,
    highlight_mask: list[bool],
    highlight_css: str,
    sub_mask: list[bool],
    wr_col: str = "WR",
) -> Styler:
    """Row-highlight top-N hero rows, dim expanded breakdown sub-rows, and color the WR column green >= 50%.

    highlight_mask/sub_mask are parallel to df's rows (by position), since a
    table can mix hero rows with inserted sub-rows whose physical position
    doesn't match the hero's rank.
    """

    def _row_style(row: pd.Series) -> list[str]:
        pos = df.index.get_loc(row.name)
        if sub_mask[pos]:
            return [SUB_ROW_CSS] * len(row)
        if highlight_mask[pos]:
            return [highlight_css] * len(row)
        return [""] * len(row)

    return (
        df.style.hide(axis="index")
        .apply(_row_style, axis=1)
        .map(lambda v: WR_GREEN if pd.notna(v) and v >= 0.5 else "", subset=[wr_col])
        .format({wr_col: lambda v: f"{v:.2%}" if pd.notna(v) else ""}, subset=[wr_col])
    )


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
