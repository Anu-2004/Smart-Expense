        y,
        f"Current Expense: Rs. {values['spent']:.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        f"Current Saving: Rs. {saving:.2f}"
    )

    y -= 35

    pdf.setFont(
        "Helvetica-Bold",
        11
    )

    pdf.drawString(
        50,
        y,
        "Expense Details"
    )

    y -= 25

    pdf.setFont(
        "Helvetica",
        9
    )

    for expense in expenses:

        line = (
            f"{expense.spent_at.strftime('%d-%m-%Y %H:%M')} | "
            f"{expense.category} | "
            f"{expense.reason} | "
            f"Rs. {expense.amount:.2f}"
        )

        pdf.drawString(
            50,
            y,
            line[:110]
        )

        y -= 18

        if y < 50:

            pdf.showPage()

            y = height - 50

            pdf.setFont(
                "Helvetica",
                9
            )

    pdf.save()

    buffer.seek(0)

    response.data = buffer.getvalue()

    return response


# =========================================================
# API - LATEST ALERT
# =========================================================

@app.route("/api/latest-alert")
@login_required
def latest_alert():

    user = get_current_user()

    alert = create_budget_alert(
        user
    )

    return jsonify(alert)


# =========================================================
# CREATE DATABASE
# =========================================================

with app.app_context():

    db.create_all()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
