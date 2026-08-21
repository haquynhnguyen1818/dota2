import pandas as pd
import streamlit as st

from app.dashboard.api_client import get_draft_suggestions, get_heroes
from app.dashboard.components.styling import GREEN, RED, style_expandable_table

MAX_PICKS = 5

st.title("Draft Suggestions")

if "opponent_picks" not in st.session_state:
    st.session_state.opponent_picks = []


def _render_suggestion_table(role: str, kind: str, suggestions: list[dict], top_n: int, top_n_css: str) -> None:
    expand_key = f"{role}_{kind}_expanded"
    last_sel_key = f"{role}_{kind}_last_sel"
    st.session_state.setdefault(expand_key, None)
    st.session_state.setdefault(last_sel_key, ())
    expanded_hero_id = st.session_state[expand_key]

    rows: list[dict] = []
    row_meta: list[tuple[str, int | None]] = []
    for s in suggestions:
        rows.append({"Hero": s["hero_name"], "WR": s["hero_wr"], "Advantage": f"{s['total_advantage'] * 100:+.2f}%"})
        row_meta.append(("hero", s["hero_id"]))
        if s["hero_id"] == expanded_hero_id:
            for b in s["breakdown"]:
                rows.append(
                    {"Hero": f"↳ vs {b['vs_hero_name']}", "WR": None, "Advantage": f"{b['advantage'] * 100:+.2f}%"}
                )
                row_meta.append(("sub", None))

    highlight_mask: list[bool] = []
    sub_mask: list[bool] = []
    hero_rank = 0
    for kind_, _ in row_meta:
        is_sub = kind_ == "sub"
        sub_mask.append(is_sub)
        highlight_mask.append(not is_sub and hero_rank < top_n)
        if not is_sub:
            hero_rank += 1

    df = pd.DataFrame(rows)
    event = st.dataframe(
        style_expandable_table(df, highlight_mask, top_n_css, sub_mask),
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{role}_{kind}",
    )

    current_selection = tuple(event.selection.rows)
    if current_selection != st.session_state[last_sel_key]:
        st.session_state[last_sel_key] = current_selection
        if current_selection:
            clicked_kind, clicked_hero_id = row_meta[current_selection[0]]
            if clicked_kind == "hero":
                st.session_state[expand_key] = None if expanded_hero_id == clicked_hero_id else clicked_hero_id
                st.rerun()
        elif expanded_hero_id is not None:
            st.session_state[expand_key] = None
            st.rerun()


heroes = get_heroes()
name_by_id = {h["id"]: h["name"] for h in heroes}
id_by_name = {h["name"]: h["id"] for h in heroes}

st.write("**Opponent picks**")
if st.session_state.opponent_picks:
    st.markdown(
        """
        <style>
        .st-key-opponent_chips div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .st-key-opponent_chips div[data-testid="stColumn"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: 0 !important;
        }
        .st-key-opponent_chips button { white-space: nowrap; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="opponent_chips"):
        chip_cols = st.columns(len(st.session_state.opponent_picks))
        for i, hid in enumerate(st.session_state.opponent_picks):
            with chip_cols[i]:
                if st.button(f"{name_by_id[hid]} ✕", key=f"remove_pick_{hid}"):
                    st.session_state.opponent_picks.remove(hid)
                    st.rerun()
else:
    st.caption("None yet.")

col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    available_names = sorted(n for n, hid in id_by_name.items() if hid not in st.session_state.opponent_picks)
    next_pick = (
        st.selectbox("Add opponent pick", available_names, index=None, placeholder="Select hero")
        if available_names
        else None
    )
with col2:
    st.write("")
    st.write("")
    if st.button("Add pick", disabled=next_pick is None or len(st.session_state.opponent_picks) >= MAX_PICKS):
        st.session_state.opponent_picks.append(id_by_name[next_pick])
        st.rerun()
with col3:
    st.write("")
    st.write("")
    if st.button("Reset"):
        st.session_state.opponent_picks = []
        st.rerun()

if st.session_state.opponent_picks:
    result = get_draft_suggestions(st.session_state.opponent_picks)
    for role_data in result["roles"]:
        st.subheader(role_data["role"])
        best_col, worst_col = st.columns(2)
        with best_col:
            st.markdown("**Top 10 best**")
            _render_suggestion_table(role_data["role"], "best", role_data["best"], 3, GREEN)
        with worst_col:
            st.markdown("**Top 10 worst**")
            _render_suggestion_table(role_data["role"], "worst", role_data["worst"], 3, RED)
