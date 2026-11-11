from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, make_response
)

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from datetime import datetime, timedelta, timezone
from functools import wraps
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

import os
import smtplib
from email.message import EmailMessage


# =========================================================
# APP CONFIGURATION
# =========================================================

app = Flask(__name__)

app.config["SECRET_KEY"] = "smart-expense-tracker-final-secret-key"

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///smart_expense_tracker.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# =========================================================
# TIME
# =========================================================

def current_time():
    """
    Return India Standard Time (IST) as a timezone-naive datetime,
    matching the existing SQLite DateTime columns.
    """
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    return utc_now + timedelta(hours=5, minutes=30)


# =========================================================
# DATABASE MODELS
# =========================================================

class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    email = db.Column(db.String(150), unique=True, nullable=False)

    phone = db.Column(db.String(30))

    password = db.Column(db.String(255), nullable=False)

    salary = db.Column(db.Float, default=0)

    location = db.Column(db.String(100))

    gender = db.Column(db.String(30))

    created_at = db.Column(
        db.DateTime,
        default=current_time
    )

    expenses = db.relationship(
        "Expense",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    savings = db.relationship(
        "Saving",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )

    notifications = db.relationship(
        "Notification",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan"
    )


class Expense(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    amount = db.Column(
        db.Float,
        nullable=False
    )

    category = db.Column(
        db.String(100),
        nullable=False
    )

    reason = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.String(500)
    )

    spent_at = db.Column(
        db.DateTime,
        default=current_time
    )


class Saving(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    amount = db.Column(
        db.Float,
        nullable=False
    )

    action = db.Column(
        db.String(20),
        nullable=False
    )

    reason = db.Column(
        db.String(250)
    )

    created_at = db.Column(
        db.DateTime,
        default=current_time
    )


class Notification(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    message = db.Column(
        db.String(500),
        nullable=False
    )

    level = db.Column(
        db.String(30),
        default="info"
    )

    created_at = db.Column(
        db.DateTime,
        default=current_time
    )

    is_read = db.Column(
        db.Boolean,
        default=False
    )


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        # Check both the session and the actual database user.
        # Render/SQLite may restart with an old browser session.
        user = get_current_user()

        if user is None:
            session.clear()

            flash(
                "Your login session has expired. Please login again.",
                "warning"
            )

            return redirect(
                url_for("login")
            )

        return function(*args, **kwargs)

    return wrapper


# =========================================================
# CURRENT USER
# =========================================================

def get_current_user():

    if "user_id" not in session:
        return None

    return db.session.get(
        User,
        session["user_id"]
    )


# =========================================================
# TOTAL EXPENSE
# =========================================================

def total_expense(user_id):

    expenses = Expense.query.filter_by(
        user_id=user_id
    ).all()

    return sum(
        expense.amount
        for expense in expenses
    )


# =========================================================
# TOTAL SAVING
# =========================================================

def total_saving(user_id):

    savings = Saving.query.filter_by(
        user_id=user_id
    ).all()

    balance = 0

    for saving in savings:

        if saving.action == "add":
            balance += saving.amount

        elif saving.action == "use":
            balance -= saving.amount

    return max(balance, 0)


# =========================================================
# MONTHLY EXPENSE
# =========================================================

def monthly_expense(user_id):

    now = current_time()

    start = datetime(
        now.year,
        now.month,
        1
    )

    expenses = Expense.query.filter(
        Expense.user_id == user_id,
        Expense.spent_at >= start
    ).all()

    return sum(
        expense.amount
        for expense in expenses
    )


# =========================================================
# BUDGET CALCULATION
# =========================================================

def budget_values(user):

    # Safety fallback. Protected routes should redirect to login
    # when the user record is missing, but this avoids a 500 error.
    if user is None:
        return {
            "salary": 0,
            "saving_target": 0,
            "expense_limit": 0,
            "spent": 0,
            "remaining": 0,
            "percentage": 0
        }

    salary = user.salary or 0

    saving_target = salary * 0.30

    expense_limit = salary * 0.70

    spent = monthly_expense(user.id)

    remaining = max(
        expense_limit - spent,
        0
    )

    if expense_limit > 0:

        percentage = (
            spent / expense_limit
        ) * 100

    else:

        percentage = 0

    return {
        "salary": salary,
        "saving_target": saving_target,
        "expense_limit": expense_limit,
        "spent": spent,
        "remaining": remaining,
        "percentage": percentage
    }


# =========================================================
# ALERT SYSTEM
# =========================================================

def create_budget_alert(user):

    if user is None:
        return {
            "level": None,
            "title": None,
            "message": None,
            "percentage": 0
        }

    values = budget_values(user)

    percentage = values["percentage"]

    level = None
    title = None
    message = None

    if percentage >= 100:

        level = "danger"

        title = "Budget Limit Exceeded"

        message = (
            f"You have used 100% or more of your "
            f"monthly expense limit. "
            f"Current spending: ₹{values['spent']:.2f}"
        )

    elif percentage >= 90:

        level = "danger"

        title = "90% Budget Alert"

        message = (
            f"You have used {percentage:.1f}% "
            f"of your monthly expense limit."
        )

    elif percentage >= 70:

        level = "warning"

        title = "70% Budget Alert"

        message = (
            f"You have reached {percentage:.1f}% "
            f"of your monthly expense limit. "
            f"Please control your spending."
        )

    elif percentage >= 50:

        level = "info"

        title = "50% Budget Alert"

        message = (
            f"You have used {percentage:.1f}% "
            f"of your monthly expense limit."
        )

    if level:

        today = current_time().date()

        existing = Notification.query.filter(
            Notification.user_id == user.id,
            Notification.title == title
        ).all()

        already_today = False

        for notification in existing:

            if notification.created_at.date() == today:
                already_today = True
                break

        if not already_today:

            notification = Notification(
                user_id=user.id,
                title=title,
                message=message,
                level=level
            )

            db.session.add(notification)

            db.session.commit()

            if percentage >= 70:
                send_email_alert(
                    user,
                    title,
                    message
                )

    return {
        "level": level,
        "title": title,
        "message": message,
        "percentage": percentage
    }


# =========================================================
# EMAIL ALERT
# =========================================================

def send_email_alert(user, subject, message):

    """
    Email configuration:

    Set these environment variables:

    MAIL_HOST
    MAIL_PORT
    MAIL_USERNAME
    MAIL_PASSWORD
    """

    host = os.environ.get("MAIL_HOST")
    port = os.environ.get("MAIL_PORT")
    username = os.environ.get("MAIL_USERNAME")
    password = os.environ.get("MAIL_PASSWORD")

    if not all([
        host,
        port,
        username,
        password
    ]):
        return False

    try:

        email = EmailMessage()

        email["Subject"] = subject

        email["From"] = username

        email["To"] = user.email

        email.set_content(
            f"""
Smart Expense Tracker

Hello {user.name},

{message}

Smart Expense Tracker
Budget Prediction System
"""
        )

        with smtplib.SMTP(
            host,
            int(port)
        ) as server:

            server.starttls()

            server.login(
                username,
                password
            )

            server.send_message(email)

        return True

    except Exception as error:

        print(
            "Email error:",
            error
        )

        return False


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("login")
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        phone = request.form.get(
            "phone",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        salary_text = request.form.get(
            "salary",
            "0"
        )

        location = request.form.get(
            "location",
            ""
        )

        gender = request.form.get(
            "gender",
            ""
        )

        if not name or not email or not password:

            flash(
                "Name, email and password are required.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        existing = User.query.filter_by(
            email=email
        ).first()

        if existing:

            flash(
                "Email already registered.",
                "danger"
            )

            return render_template(
                "register.html"
            )

        try:

            salary = float(
                salary_text or 0
            )

        except ValueError:

            salary = 0

        user = User(
            name=name,
            email=email,
            phone=phone,
            password=generate_password_hash(
                password
            ),
            salary=salary,
            location=location,
            gender=gender
        )

        db.session.add(user)

        db.session.commit()

        flash(
            "Account created successfully. Please login.",
            "success"
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password,
            password
        ):

            session["user_id"] = user.id

            session["login_time"] = (
                current_time().strftime(
                    "%d-%m-%Y %I:%M %p"
                )
            )

            flash(
                "Login successful.",
                "success"
            )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Invalid email or password.",
            "danger"
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "info"
    )

    return redirect(
        url_for("login")
    )


# =========================================================
# PROFILE
# =========================================================

@app.route(
    "/profile",
    methods=["GET", "POST"]
)
@login_required
def profile():

    user = get_current_user()

    if request.method == "POST":

        user.name = request.form.get(
            "name",
            user.name
        ).strip()

        user.phone = request.form.get(
            "phone",
            user.phone
        ).strip()

        user.location = request.form.get(
            "location",
            user.location
        ).strip()

        user.gender = request.form.get(
            "gender",
            user.gender
        )

        try:

            user.salary = float(
                request.form.get(
                    "salary",
                    user.salary
                )
            )

        except ValueError:

            flash(
                "Invalid salary.",
                "danger"
            )

            return redirect(
                url_for("profile")
            )

        db.session.commit()

        flash(
            "Profile updated successfully.",
            "success"
        )

        return redirect(
            url_for("profile")
        )

    return render_template(
        "profile.html",
        user=user
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    user = get_current_user()

    values = budget_values(user)

    saving = total_saving(
        user.id
    )

    all_expenses = Expense.query.filter_by(
        user_id=user.id
    ).order_by(
        Expense.spent_at.desc()
    ).all()

    recent_expenses = all_expenses[:5]

    total_income = user.salary or 0

    total_expense = sum(expense.amount for expense in all_expenses)

    remaining_balance = total_income - total_expense

    recent_savings = Saving.query.filter_by(
        user_id=user.id
    ).order_by(
        Saving.created_at.desc()
    ).limit(5).all()

    categories = {}

    for expense in all_expenses:

        categories[
            expense.category
        ] = categories.get(
            expense.category,
            0
        ) + expense.amount

    alert = create_budget_alert(user)

    return render_template(
        "dashboard.html",
        user=user,
        values=values,
        saving=saving,
        remaining_balance=remaining_balance,
        recent_expenses=recent_expenses,
        recent_savings=recent_savings,
        categories=categories,
        alert=alert
    )

# =========================================================
# ADD EXPENSE
# =========================================================

@app.route(
    "/expense",
    methods=["GET", "POST"]
)
@login_required
def expense():

    user = get_current_user()

    if request.method == "POST":

        amount_text = request.form.get(
            "amount",
            "0"
        )

        category = request.form.get(
            "category",
            "Other"
        )

        reason = request.form.get(
            "reason",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        try:

            amount = float(
                amount_text
            )

        except ValueError:

            amount = 0

        if amount <= 0:

            flash(
                "Enter a valid expense amount.",
                "danger"
            )

            return redirect(
                url_for("expense")
            )

        if not reason:

            flash(
                "Please enter the expense reason.",
                "danger"
            )

            return redirect(
                url_for("expense")
            )

        values_before = budget_values(
            user
        )

        projected_spent = (
            values_before["spent"]
            + amount
        )

        limit = values_before[
            "expense_limit"
        ]

        crossed_70 = (
            limit > 0
            and values_before["spent"] < limit * 0.70
            and projected_spent >= limit * 0.70
        )

        if crossed_70 and not reason:

            flash(
                "Reason is required when crossing 70% budget.",
                "danger"
            )

            return redirect(
                url_for("expense")
            )

        new_expense = Expense(
            user_id=user.id,
            amount=amount,
            category=category,
            reason=reason,
            description=description,
            spent_at=current_time()
        )

        db.session.add(
            new_expense
        )

        db.session.commit()

        alert = create_budget_alert(
            user
        )

        if (
            alert["percentage"] >= 70
            and reason
        ):

            pass

        flash(
            "Expense added successfully.",
            "success"
        )

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "expense.html",
        user=user
    )

# =========================================================
# MULTIPLE EXPENSE
# =========================================================

@app.route(
    "/expense/multiple",
    methods=["POST"]
)
@login_required
def multiple_expense():

    user = get_current_user()

    amounts = request.form.getlist(
        "amount[]"
    )

    categories = request.form.getlist(
        "category[]"
    )

    reasons = request.form.getlist(
        "reason[]"
    )

    descriptions = request.form.getlist(
        "description[]"
    )

    added = 0

    for index, amount_text in enumerate(
        amounts
    ):

        try:

            amount = float(
                amount_text
            )

        except ValueError:

            continue

        if amount <= 0:
            continue

        category = (
            categories[index]
            if index < len(categories)
            else "Other"
        )

        reason = (
            reasons[index]
            if index < len(reasons)
            else ""
        ).strip()

        description = (
            descriptions[index]
            if index < len(descriptions)
            else ""
        ).strip()

        if not reason:
            continue

        item = Expense(
            user_id=user.id,
            amount=amount,
            category=category,
            reason=reason,
            description=description,
            spent_at=current_time()
        )

        db.session.add(item)

        added += 1

    db.session.commit()

    create_budget_alert(user)

    flash(
        f"{added} expense(s) added successfully.",
        "success"
    )

    return redirect(
        url_for("expenses")
    )


# =========================================================
# EXPENSE LIST
# =========================================================

@app.route("/expenses")
@login_required
def expenses():

    user = get_current_user()

    search = request.args.get(
        "search",
        ""
    ).strip()

    category = request.args.get(
        "category",
        ""
    ).strip()

    query = Expense.query.filter_by(
        user_id=user.id
    )

    if search:

        query = query.filter(
            db.or_(
                Expense.reason.ilike(
                    f"%{search}%"
                ),
                Expense.description.ilike(
                    f"%{search}%"
                )
            )
        )

    if category:

        query = query.filter_by(
            category=category
        )

    expense_list = query.order_by(
        Expense.spent_at.desc()
    ).all()

    return render_template(
        "expenses.html",
        expenses=expense_list,
        search=search,
        category=category
    )


# =========================================================
# EDIT EXPENSE
# =========================================================

@app.route(
    "/expense/edit/<int:expense_id>",
    methods=["GET", "POST"]
)
@login_required
def edit_expense(expense_id):

    user = get_current_user()

    item = Expense.query.filter_by(
        id=expense_id,
        user_id=user.id
    ).first_or_404()

    if request.method == "POST":

        try:

            item.amount = float(
                request.form.get(
                    "amount",
                    item.amount
                )
            )

        except ValueError:

            flash(
                "Invalid amount.",
                "danger"
            )

            return redirect(
                url_for(
                    "edit_expense",
                    expense_id=item.id
                )
            )

        item.category = request.form.get(
            "category",
            item.category
        )

        item.reason = request.form.get(
            "reason",
            item.reason
        ).strip()

        item.description = request.form.get(
            "description",
            item.description
        ).strip()

        db.session.commit()

        create_budget_alert(user)

        flash(
            "Expense updated successfully.",
            "success"
        )

        return redirect(
            url_for("expenses")
        )

    return render_template(
        "edit_expense.html",
        expense=item
    )


# =========================================================
# DELETE EXPENSE
# =========================================================

@app.route(
    "/expense/delete/<int:expense_id>",
    methods=["POST"]
)
@login_required
def delete_expense(expense_id):

    user = get_current_user()

    item = Expense.query.filter_by(
        id=expense_id,
        user_id=user.id
    ).first_or_404()

    db.session.delete(item)

    db.session.commit()

    flash(
        "Expense deleted successfully.",
        "success"
    )

    return redirect(
        url_for("expenses")
    )


# =========================================================
# SAVINGS
# =========================================================

@app.route(
    "/savings",
    methods=["GET", "POST"]
)
@login_required
def savings():

    user = get_current_user()

    if request.method == "POST":

        action = request.form.get(
            "action",
            "add"
        )

        try:

            amount = float(
                request.form.get(
                    "amount",
                    0
                )
            )

        except ValueError:

            amount = 0

        reason = request.form.get(
            "reason",
            ""
        ).strip()

        balance = total_saving(
            user.id
        )

        if amount <= 0:

            flash(
                "Enter a valid saving amount.",
                "danger"
            )

            return redirect(
                url_for("savings")
            )

        if not reason:

            flash(
                "Saving reason is required.",
                "danger"
            )

            return redirect(
                url_for("savings")
            )

        if action == "use":

            if amount > balance:

                flash(
                    "You cannot use more than your current saving.",
                    "danger"
                )

                return redirect(
                    url_for("savings")
                )

        item = Saving(
            user_id=user.id,
            amount=amount,
            action=action,
            reason=reason,
            created_at=current_time()
        )

        db.session.add(item)

        db.session.commit()

        flash(
            "Saving transaction added successfully.",
            "success"
        )

        return redirect(
            url_for("savings")
        )

    history = Saving.query.filter_by(
        user_id=user.id
    ).order_by(
        Saving.created_at.desc()
    ).all()

    balance = total_saving(
        user.id
    )

    values = budget_values(
        user
    )

    return render_template(
        "savings.html",
        history=history,
        balance=balance,
        target=values["saving_target"]
    )


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/notifications")
@login_required
def notifications():

    user = get_current_user()

    notification_list = Notification.query.filter_by(
        user_id=user.id
    ).order_by(
        Notification.created_at.desc()
    ).all()

    return render_template(
        "notifications.html",
        notifications=notification_list
    )


# =========================================================
# MARK NOTIFICATIONS READ
# =========================================================

@app.route(
    "/notifications/read",
    methods=["POST"]
)
@login_required
def mark_notifications_read():

    user = get_current_user()

    Notification.query.filter_by(
        user_id=user.id,
        is_read=False
    ).update(
        {
            "is_read": True
        }
    )

    db.session.commit()

    return redirect(
        url_for("notifications")
    )

# =========================================================
# ANALYTICS
# =========================================================

@app.route("/analytics")
@login_required
def analytics():

    user = get_current_user()

    expenses = Expense.query.filter_by(
        user_id=user.id
    ).all()

    category_totals = {}

    monthly_totals = {}

    for expense in expenses:

        category_totals[
            expense.category
        ] = category_totals.get(
            expense.category,
            0
        ) + expense.amount

        month = expense.spent_at.strftime(
            "%Y-%m"
        )

        monthly_totals[
            month
        ] = monthly_totals.get(
            month,
            0
        ) + expense.amount

    total = sum(
        category_totals.values()
    )

    category_percentages = {}

    for key, value in category_totals.items():

        if total > 0:

            category_percentages[key] = (
                value / total
            ) * 100

        else:

            category_percentages[key] = 0

    return render_template(
        "analytics.html",
        category_totals=category_totals,
        category_percentages=category_percentages,
        monthly_totals=monthly_totals,
        total=total
    )

# =========================================================
# BUDGET PREDICTION
# =========================================================

def predict_next_month(expenses):

    if not expenses:

        return 0

    monthly = {}

    for expense in expenses:

        month = expense.spent_at.strftime(
            "%Y-%m"
        )

        monthly[month] = (
            monthly.get(month, 0)
            + expense.amount
        )

    values = list(
        monthly.values()
    )

    if len(values) == 1:

        return values[0]

    # Simple linear regression
    n = len(values)

    x = list(
        range(1, n + 1)
    )

    x_mean = sum(x) / n

    y_mean = sum(values) / n

    numerator = sum(
        (
            x[i] - x_mean
        ) *
        (
            values[i] - y_mean
        )
        for i in range(n)
    )

    denominator = sum(
        (
            x_value - x_mean
        ) ** 2
        for x_value in x
    )

    if denominator == 0:

        return y_mean

    slope = (
        numerator /
        denominator
    )

    intercept = (
        y_mean -
        slope * x_mean
    )

    prediction = (
        slope * (n + 1)
        + intercept
    )

    return max(
        prediction,
        0
    )


@app.route("/prediction")
@login_required
def prediction():

    user = get_current_user()

    expenses = Expense.query.filter_by(
        user_id=user.id
    ).order_by(
        Expense.spent_at.asc()
    ).all()

    predicted = predict_next_month(
        expenses
    )

    values = budget_values(
        user
    )

    limit = values[
        "expense_limit"
    ]

    if predicted > limit and limit > 0:

        status = "High Risk"

        message = (
            "Predicted spending is above "
            "your 70% monthly expense limit."
        )

    elif (
        predicted > limit * 0.8
        and limit > 0
    ):

        status = "Medium Risk"

        message = (
            "Your predicted spending is "
            "approaching the budget limit."
        )

    else:

        status = "Low Risk"

        message = (
            "Your predicted spending is "
            "within the planned budget."
        )

    return render_template(
        "prediction.html",
        predicted=predicted,
        limit=limit,
        status=status,
        message=message,
        expenses=expenses
    )


# =========================================================
# PDF REPORT
# =========================================================

@app.route("/report.pdf")
@login_required
def report_pdf():

    user = get_current_user()

    expenses = Expense.query.filter_by(
        user_id=user.id
    ).order_by(
        Expense.spent_at.desc()
    ).all()

    values = budget_values(
        user
    )

    saving = total_saving(
        user.id
    )

    response = make_response()

    response.headers[
        "Content-Type"
    ] = "application/pdf"

    response.headers[
        "Content-Disposition"
    ] = (
        "attachment; filename=expense_report.pdf"
    )

    from io import BytesIO

    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=A4
    )

    width, height = A4

    y = height - 50

    pdf.setFont(
        "Helvetica-Bold",
        20
    )

    pdf.drawString(
        50,
        y,
        "Smart Expense Tracker"
    )

    y -= 30

    pdf.setFont(
        "Helvetica",
        11
    )

    pdf.drawString(
        50,
        y,
        "Budget Prediction Report"
    )

    y -= 35

    pdf.drawString(
        50,
        y,
        f"Name: {user.name}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        f"Email: {user.email}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Monthly Income: Rs. {user.salary:.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        f"Expense Limit (70%): Rs. {values['expense_limit']:.2f}"
    )

    y -= 20

    pdf.drawString(
        50,
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