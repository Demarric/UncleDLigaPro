
from flask import Flask, render_template, request, redirect, flash, session
import os
import sqlite3
from datetime import date, datetime

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

INITIAL_RATING = 1000
K_FACTOR = 24


def connect_db():
    conn = sqlite3.connect("liga_pro.db")
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    conn = connect_db()
    cursor = conn.cursor()

    # Preserve existing prediction records.
    columns = [
        row["name"]
        for row in cursor.execute("PRAGMA table_info(predictions)")
    ]

    if "match_id" not in columns:
        cursor.execute(
            "ALTER TABLE predictions ADD COLUMN match_id INTEGER"
        )

    # Scheduled fixtures.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fixtures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1 TEXT NOT NULL,
            player2 TEXT NOT NULL,
            scheduled_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'UPCOMING',
            winner TEXT,
            completed_match_id INTEGER
        )
    """)

    # Add fixture_id to predictions without deleting old data.
    columns = [
        row["name"]
        for row in cursor.execute("PRAGMA table_info(predictions)")
    ]

    if "fixture_id" not in columns:
        cursor.execute(
            "ALTER TABLE predictions ADD COLUMN fixture_id INTEGER"
        )

    conn.commit()
    conn.close()


def calculate_ratings():
    conn = connect_db()
    matches = conn.execute("""
        SELECT * FROM matches
        ORDER BY match_date ASC, id ASC
    """).fetchall()
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


def get_dashboard_data():
    conn = connect_db()
    cursor = conn.cursor()

    matches = cursor.execute("""
        SELECT * FROM matches ORDER BY id DESC
    """).fetchall()

    fixtures = cursor.execute("""
        SELECT * FROM fixtures
        ORDER BY scheduled_date ASC, id ASC
    """).fetchall()

    player_count = cursor.execute(
        "SELECT COUNT(*) FROM players"
    ).fetchone()[0]

    match_count = cursor.execute(
        "SELECT COUNT(*) FROM matches"
    ).fetchone()[0]

    prediction_count = cursor.execute(
        "SELECT COUNT(*) FROM predictions"
    ).fetchone()[0]

    correct_count = cursor.execute("""
        SELECT COUNT(*) FROM predictions
        WHERE evaluated = 1
        AND predicted_winner = actual_winner
    """).fetchone()[0]

    incorrect_count = cursor.execute("""
        SELECT COUNT(*) FROM predictions
        WHERE evaluated = 1
        AND predicted_winner != actual_winner
    """).fetchone()[0]

    pending_count = cursor.execute("""
        SELECT COUNT(*) FROM predictions
        WHERE evaluated = 0
    """).fetchone()[0]

    evaluated_count = correct_count + incorrect_count

    accuracy = (
        round(correct_count / evaluated_count * 100, 1)
        if evaluated_count else 0
    )

    prediction_history = cursor.execute("""
        SELECT p.*, f.scheduled_date AS fixture_date
        FROM predictions p
        LEFT JOIN fixtures f ON p.fixture_id = f.id
        ORDER BY p.id DESC
    """).fetchall()

    # Daily prediction accuracy, grouped by prediction date.
    trend_rows = cursor.execute("""
        SELECT
            prediction_date,
            COUNT(*) AS evaluated,
            SUM(
                CASE
                    WHEN predicted_winner = actual_winner THEN 1
                    ELSE 0
                END
            ) AS correct
        FROM predictions
        WHERE evaluated = 1
        AND actual_winner IS NOT NULL
        GROUP BY prediction_date
        ORDER BY prediction_date ASC
    """).fetchall()

    accuracy_trend = []

    for row in trend_rows:
        day_evaluated = row[1]
        day_correct = row[2] or 0

        accuracy_trend.append({
            "date": row[0],
            "evaluated": day_evaluated,
            "correct": day_correct,
            "accuracy": round(
                day_correct / day_evaluated * 100, 1
            ) if day_evaluated else 0
        })

    # Prediction leaderboard grouped by predicted winner.
    leaderboard_rows = cursor.execute("""
        SELECT
            predicted_winner,
            COUNT(*) AS evaluated,
            SUM(
                CASE
                    WHEN predicted_winner = actual_winner THEN 1
                    ELSE 0
                END
            ) AS correct
        FROM predictions
        WHERE evaluated = 1
        AND actual_winner IS NOT NULL
        AND predicted_winner IS NOT NULL
        GROUP BY predicted_winner
    """).fetchall()

    prediction_leaderboard = []

    for row in leaderboard_rows:
        player_evaluated = row[1]
        player_correct = row[2] or 0

        prediction_leaderboard.append({
            "player": row[0],
            "evaluated": player_evaluated,
            "correct": player_correct,
            "accuracy": round(
                player_correct / player_evaluated * 100, 1
            ) if player_evaluated else 0
        })

    prediction_leaderboard.sort(
        key=lambda item: (
            item["accuracy"],
            item["evaluated"]
        ),
        reverse=True
    )

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

    player_stats.sort(
        key=lambda x: x["rating"],
        reverse=True
    )

    analytics = {
        "prediction_count": prediction_count,
        "correct": correct_count,
        "incorrect": incorrect_count,
        "pending": pending_count,
        "evaluated": evaluated_count,
        "accuracy": accuracy
    }

    return (
        matches,
        player_stats,
        match_count,
        player_count,
        analytics,
        prediction_history,
        fixtures,
        accuracy_trend,
        prediction_leaderboard
    )


@app.route("/", methods=["GET", "POST"])
def dashboard():

    if request.method == "POST":
        player1 = request.form.get("player1", "").strip()
        player2 = request.form.get("player2", "").strip()
        choice = request.form.get("winner", "")
        match_date = request.form.get("match_date", "")

        winner = (
            player1 if choice == "player1"
            else player2 if choice == "player2"
            else ""
        )

        if not all([player1, player2, winner, match_date]):
            flash("Complete all match result fields.")

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

            flash("Completed match saved. No unrelated predictions were evaluated.")

        return redirect("/")

    prediction = session.pop("prediction", None)
    return render_dashboard(prediction)


def render_dashboard(prediction=None):
    data = get_dashboard_data()

    return render_template(
        "index.html",
        matches=data[0],
        player_stats=data[1],
        match_count=data[2],
        player_count=data[3],
        analytics=data[4],
        prediction_history=data[5],
        fixtures=data[6],
        accuracy_trend=data[7],
        prediction_leaderboard=data[8],
        today=date.today().isoformat(),
        prediction=prediction
    )


@app.route("/fixture", methods=["POST"])
def create_fixture():
    player1 = request.form.get("player1", "").strip()
    player2 = request.form.get("player2", "").strip()
    scheduled_date = request.form.get("scheduled_date", "")

    if not all([player1, player2, scheduled_date]):
        flash("Complete all fixture fields.")

    elif player1.lower() == player2.lower():
        flash("Choose two different players.")

    else:
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO fixtures
            (player1, player2, scheduled_date)
            VALUES (?, ?, ?)
        """, (player1, player2, scheduled_date))

        for player in [player1, player2]:
            cursor.execute("""
                INSERT OR IGNORE INTO players (name)
                VALUES (?)
            """, (player,))

        conn.commit()
        conn.close()

        flash("Fixture created successfully.")

    return redirect("/")


@app.route("/predict", methods=["POST"])
def predict():
    player1 = request.form.get("player1", "").strip()
    player2 = request.form.get("player2", "").strip()
    fixture_value = request.form.get("fixture_id", "").strip()

    if not player1 or not player2 or player1.lower() == player2.lower():
        flash("Choose two different players.")
        return redirect("/")

    fixture_id = None

    if fixture_value:
        try:
            fixture_id = int(fixture_value)
        except ValueError:
            flash("Invalid fixture selected.")
            return redirect("/")

        conn = connect_db()
        fixture = conn.execute("""
            SELECT * FROM fixtures
            WHERE id = ? AND status = 'UPCOMING'
        """, (fixture_id,)).fetchone()
        conn.close()

        if (
            fixture is None
            or fixture["player1"] != player1
            or fixture["player2"] != player2
        ):
            flash("The selected fixture does not match these players.")
            return redirect("/")

    ratings, records, all_matches = calculate_ratings()

    rating1 = ratings.get(player1, INITIAL_RATING)
    rating2 = ratings.get(player2, INITIAL_RATING)

    expected1 = 1 / (1 + 10 ** ((rating2 - rating1) / 400))

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

    cursor = conn.execute("""
        INSERT INTO predictions (
            player1, player2, probability1, probability2,
            predicted_winner, prediction_date, evaluated,
            fixture_id
        )
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (
        player1, player2, probability1, probability2,
        predicted_winner, date.today().isoformat(), fixture_id
    ))

    prediction_id = cursor.lastrowid

    conn.commit()
    conn.close()

    prediction = {
        "id": prediction_id,
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

    session["prediction"] = prediction
    return redirect("/")


@app.route("/fixture/<int:fixture_id>/result", methods=["POST"])
def complete_fixture(fixture_id):
    winner = request.form.get("winner", "").strip()
    match_date = request.form.get("match_date", "").strip()

    conn = connect_db()
    cursor = conn.cursor()

    fixture = cursor.execute("""
        SELECT * FROM fixtures
        WHERE id = ? AND status = 'UPCOMING'
    """, (fixture_id,)).fetchone()

    if fixture is None:
        conn.close()
        flash("Fixture not found or already completed.")
        return redirect("/")

    player1 = fixture["player1"]
    player2 = fixture["player2"]

    if winner not in [player1, player2] or not match_date:
        conn.close()
        flash("Choose a valid winner and match date.")
        return redirect("/")

    cursor.execute("""
        INSERT INTO matches
        (player1, player2, winner, match_date)
        VALUES (?, ?, ?, ?)
    """, (player1, player2, winner, match_date))

    match_id = cursor.lastrowid

    cursor.execute("""
        UPDATE fixtures
        SET status = 'COMPLETED',
            winner = ?,
            completed_match_id = ?
        WHERE id = ?
    """, (winner, match_id, fixture_id))

    # Only predictions linked to this exact fixture are evaluated.
    cursor.execute("""
        UPDATE predictions
        SET actual_winner = ?,
            evaluated = 1,
            match_id = ?
        WHERE fixture_id = ?
        AND evaluated = 0
    """, (winner, match_id, fixture_id))

    conn.commit()
    conn.close()

    flash("Fixture completed. Its linked predictions have been evaluated.")
    return redirect("/")


initialize_database()


if __name__ == "__main__":
    app.run(debug=True)
