"""Rank hero-vs-opponent matchup advantage per role (Carry/Midlane/Offlane).

For each opponent, ranks all heroes in a role list from best matchup
(rank 1) to worst, using log5 (Bill James) expected win rate to isolate
matchup-specific edge from each hero's win rate over the latest 2 weeks.
See dota2_ranking_adv.txt for the spec.
"""
import psycopg

from app.config import creds_opendota

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS hero_matchup_advantage (
    role_name TEXT NOT NULL,
    hero_id INTEGER NOT NULL,
    vs_hero_id INTEGER NOT NULL,
    wr_a_b NUMERIC,
    hero_wr NUMERIC,
    vs_hero_wr NUMERIC,
    xwr_a_b NUMERIC,
    advantage NUMERIC,
    rank_vs_hero INTEGER,
    PRIMARY KEY (role_name, hero_id, vs_hero_id)
)
"""

COMPUTE_AND_INSERT = """
WITH ranked_weeks AS (
    SELECT hero_id, wins, games_played,
           ROW_NUMBER() OVER (PARTITION BY hero_id ORDER BY week DESC) AS rn
    FROM stratz_hero_win_week
),
latest_hero_wr AS (
    SELECT hero_id, SUM(wins)::numeric / SUM(games_played) AS wr
    FROM ranked_weeks
    WHERE rn <= 2
    GROUP BY hero_id
),
role_heroes AS (
    SELECT hr.hero_id, r.role_name
    FROM hero_roles_csv_import hr
    JOIN roles_csv_import r ON r.role_id = hr.role_id
    WHERE r.role_name IN ('Carry', 'Midlane', 'Offlane')
),
matchup_calc AS (
    SELECT
        rh.role_name,
        m.hero_id,
        m.vs_hero_id,
        m.wins::numeric / m.games_played AS wr_a_b,
        hw_a.wr AS hero_wr,
        hw_b.wr AS vs_hero_wr
    FROM role_heroes rh
    JOIN stratz_hero_matchups m ON m.hero_id = rh.hero_id
    JOIN latest_hero_wr hw_a ON hw_a.hero_id = m.hero_id
    JOIN latest_hero_wr hw_b ON hw_b.hero_id = m.vs_hero_id
),
with_xwr AS (
    SELECT
        *,
        (hero_wr * (1 - vs_hero_wr))
            / (hero_wr * (1 - vs_hero_wr) + (1 - hero_wr) * vs_hero_wr) AS xwr_a_b
    FROM matchup_calc
)
INSERT INTO hero_matchup_advantage
    (role_name, hero_id, vs_hero_id, wr_a_b, hero_wr, vs_hero_wr, xwr_a_b, advantage, rank_vs_hero)
SELECT
    role_name,
    hero_id,
    vs_hero_id,
    wr_a_b,
    hero_wr,
    vs_hero_wr,
    xwr_a_b,
    wr_a_b - xwr_a_b AS advantage,
    RANK() OVER (PARTITION BY role_name, vs_hero_id ORDER BY (wr_a_b - xwr_a_b) DESC) AS rank_vs_hero
FROM with_xwr
"""


def main() -> None:
    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode=creds_opendota.get("sslmode", "require"),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            cur.execute("TRUNCATE hero_matchup_advantage")
            cur.execute(COMPUTE_AND_INSERT)
            cur.execute("SELECT count(*) FROM hero_matchup_advantage")
            count = cur.fetchone()[0]
        conn.commit()

        print(f"Loaded {count} hero_matchup_advantage rows.")


if __name__ == "__main__":
    main()
