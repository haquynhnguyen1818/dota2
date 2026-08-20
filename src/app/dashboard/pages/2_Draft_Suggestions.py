import pandas as pd
import streamlit as st

from app.dashboard.api_client import get_draft_suggestions, get_heroes
from app.dashboard.components.styling import GREEN, RED, highlight_top_n

MAX_PICKS = 5

st.title("Draft Suggestions")

if "opponent_picks" not in st.session_state:
    st.session_state.opponent_picks = []

heroes = get_heroes()
name_by_id = {h["id"]: h["name"] for h in heroes}
id_by_name = {h["name"]: h["id"] for h in heroes}

picked_names = [name_by_id[hid] for hid in st.session_state.opponent_picks]
st.write("Opponent picks so far:", ", ".join(picked_names) if picked_names else "none")

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
        best_df = pd.DataFrame(
            [{"Hero": s["hero_name"], "Advantage": f"{s['total_advantage'] * 100:+.2f}%"} for s in role_data["best"]]
        )
        worst_df = pd.DataFrame(
            [{"Hero": s["hero_name"], "Advantage": f"{s['total_advantage'] * 100:+.2f}%"} for s in role_data["worst"]]
        )
        best_col, worst_col = st.columns(2)
        with best_col:
            st.markdown("**Top 10 best**")
            st.table(highlight_top_n(best_df, 3, GREEN))
        with worst_col:
            st.markdown("**Top 10 worst**")
            st.table(highlight_top_n(worst_df, 3, RED))
