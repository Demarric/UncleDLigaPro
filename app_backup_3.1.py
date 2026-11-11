
from flask import Flask, render_template, request, redirect, flash
import sqlite3
from datetime import date

app = Flask(__name__)
app.secret_key = "uncled_liga_pro_2026"

INITIAL_RATING = 1000
K_FACTOR = 24


def connect_db():
    conn = sqlite3.connect("liga_pro.db")
    conn.row_factory = sqlite3.Row
    return conn


def calculate_ratings():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM matches
        ORDER BY match_date ASC, id ASC
    """)
    matches = cursor.fetchall()
    conn.close()

    ratings = {}
    records = {}

    for match in matches:
        p1 = match["player1"]
        p2 = match["player2"]
        winner = match["winner"]

        for player in [p1, p2]:
            if player not in ratings:
                ratings[player] = INITIAL_RATING
                records[player] = []

        old1 = ratings[p1]
        old2 = ratings[p2]

        expected1 = 1 / (1 + 10 ** ((old2 - old1) / 400))
        expected2 = 1 - expected1

        actual1 = 1 if winner == p1 else 0
        actual2 = 1 - actual1

        ratings[p1] = old1 + K_FACTOR * (actual1 - expected1)
        ratings[p2] = old2 + K_FACTOR * (actual2 - expected2)

        records[p1].append("W" if winner == p1 else "L")
        records[p2].append("W" if winner == p2 else "L")

    return ratings, records, matches


def evaluate_predictions(player1, player2, winner, match_date):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE predictions
        SET actual_winner = ?, evaluated = 1
        WHERE evaluated = 0
        AND prediction_date <= ?
        AND (
            (player1 = ? AND player2 = ?)
            OR
            (player1 = ? AND player2 = ?)
        )
    """, (
        winner, match_date,
        player1, player2,
        player2, player1
    ))

    conn.commit()
    conn.close()


def get_dashboard_data():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM matches ORDER BY id DESC")
    matches = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM matches")
    match_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM players")
    player_count = cursor.fetchone()[0]

    conn.close()

    ratings, records, all_matches = calculate_ratings()

    player_stats = []

    for player, history in records.items():
        played = len(history)
        wins = history.count("W")
        losses = played - wins

        player_stats.append({
            "name": player,
            "played": played,
            "wins": wins,
            "losses": losses,
            "percentage": round(wins / played * 100, 1),
            "rating": round(ratings[player]),
            "form": " ".join(history[-5:])
        })

    player_stats.sort(key=lambda x: x["rating"], reverse=True)

    return matches, player_stats, match_count, player_count


@app.route("/", methods=["GET", "POST"])
def dashboard():

    if request.method == "POST":
        player1 = request.form.get("player1", "").strip()
        player2 = request.form.get("player2", "").strip()
        choice = request.form.get("winner", "")
        match_date = request.form.get("match_date", "")

        if choice == "player1":
            winner = player1
        elif choice == "player2":
            winner = player2
        else:
            winner = ""

        if not all([player1, player2, winner, match_date]):
            flash("Complete all fields.")

        elif player1.lower() == player2.lower():
            flash("Enter two different players.")

        else:
            conn = connect_db()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO matches
                (player1, player2, winner, match_date)
                VALUES (?, ?, ?, ?)
            """, (player1, player2, winner, match_date))

            for player in [player1, player2]:
                cursor.execute("""
                    INSERT OR IGNORE INTO players (name)
                    VALUES (?)
                """, (player,))

            conn.commit()
            conn.close()

            evaluate_predictions(
                player1, player2, winner, match_date
            )

            flash("Match saved successfully!")

        return redirect("/")

    matches, player_stats, match_count, player_count = get_dashboard_data()

    return render_template(
        "index.html",
        matches=matches,
        player_stats=player_stats,
        player_count=player_count,
        match_count=match_count,
        today=date.today().isoformat(),
        prediction=None
    )


@app.route("/predict", methods=["POST"])
def predict():

    player1 = request.form.get("player1", "").strip()
    player2 = request.form.get("player2", "").strip()

    prediction = None

    if not player1 or not player2 or player1.lower() == player2.lower():
        flash("Choose two different players.")

    else:
        ratings, records, all_matches = calculate_ratings()

        rating1 = ratings.get(player1, INITIAL_RATING)
        rating2 = ratings.get(player2, INITIAL_RATING)

        expected1 = 1 / (
            1 + 10 ** ((rating2 - rating1) / 400)
        )

        probability1 = round(expected1 * 100, 1)
        probability2 = round(100 - probability1, 1)

        history1 = records.get(player1, [])
        history2 = records.get(player2, [])

        h2h_matches = [
            m for m in all_matches
            if {m["player1"], m["player2"]} == {player1, player2}
        ]

        h2h_wins1 = sum(
            1 for m in h2h_matches if m["winner"] == player1
        )

        h2h_wins2 = sum(
            1 for m in h2h_matches if m["winner"] == player2
        )

        total_played = len(history1) + len(history2)

        if total_played < 5:
            confidence = "LOW – Not enough match history"
        elif total_played < 15:
            confidence = "LIMITED – More results needed"
        else:
            confidence = "BETTER DATA – Still not guaranteed"

        predicted_winner = (
            player1 if probability1 >= probability2 else player2
        )

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO predictions (
                player1,
                player2,
                probability1,
                probability2,
                predicted_winner,
                prediction_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            player1,
            player2,
            probability1,
            probability2,
            predicted_winner,
            date.today().isoformat()
        ))

        conn.commit()
        conn.close()

        prediction = {
            "player1": player1,
            "player2": player2,
            "rating1": round(rating1),
            "rating2": round(rating2),
            "probability1": probability1,
            "probability2": probability2,
            "predicted_winner": predicted_winner,
            "form1": " ".join(history1[-5:]) or "No matches",
            "form2": " ".join(history2[-5:]) or "No matches",
            "h2h_total": len(h2h_matches),
            "h2h_wins1": h2h_wins1,
            "h2h_wins2": h2h_wins2,
            "confidence": confidence
        }

    matches, player_stats, match_count, player_count = get_dashboard_data()

    return render_template(
        "index.html",
        matches=matches,
        player_stats=player_stats,
        player_count=player_count,
        match_count=match_count,
        today=date.today().isoformat(),
        prediction=prediction
    )


if __name__ == "__main__":
    app.run(debug=True)
