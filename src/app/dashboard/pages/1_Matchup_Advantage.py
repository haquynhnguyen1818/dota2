import pandas as pd
import streamlit as st

from app.dashboard.api_client import get_heroes, get_matchup_advantage
from app.dashboard.components.styling import highlight_best_and_worst

st.title("Matchup Advantage")

heroes = get_heroes()
name_by_id = {h["id"]: h["name"] for h in heroes}
id_by_name = {h["name"]: h["id"] for h in heroes}

role = st.selectbox("Your role", ["Carry", "Midlane", "Offlane"], index=None, placeholder="Select role")
opponent_name = st.selectbox(
    "Opponent hero", sorted(id_by_name), index=None, placeholder="Select opponent hero"
)

if role and opponent_name:
    rows = get_matchup_advantage(role, id_by_name[opponent_name])
    df = pd.DataFrame(
        [
            {
                "Rank": r["rank_vs_hero"],
                "Hero": r["hero_name"],
                "Advantage": f"{r['advantage'] * 100:+.2f}%",
                "Hero WR": f"{r['hero_wr'] * 100:.2f}%",
                "vs Hero WR": f"{r['vs_hero_wr'] * 100:.2f}%",
            }
            for r in rows
        ]
    )
    st.table(highlight_best_and_worst(df))
else:
    st.info("Select a role and an opponent hero to see the ranking.")
