import os
import json
import hmac
import re
import secrets
import smtplib
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Flask, flash, jsonify, render_template, request, redirect, url_for, session
from mysql.connector import Error as MySQLDatabaseError
from database import get_connection
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash,check_password_hash

load_dotenv(Path(__file__).with_name(".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
if not app.secret_key:
    app.secret_key = secrets.token_urlsafe(48)
    app.logger.warning(
        "FLASK_SECRET_KEY is not configured; sessions will expire when Flask restarts."
    )

CHAT_RATE_LIMIT = 15
CHAT_RATE_WINDOW_SECONDS = 60
CHAT_MAX_MESSAGE_LENGTH = 1200
CHAT_MAX_HISTORY = 8
chat_requests_by_ip = defaultdict(deque)
COMPLAINT_RATE_LIMIT = 3
COMPLAINT_RATE_WINDOW_SECONDS = 3600
complaint_requests_by_ip = defaultdict(deque)
WEBSITE_FAQS = (
    (
        "What is SchemeMate?",
        ("what is schememate", "what does schememate do"),
        "SchemeMate helps you explore government schemes that may fit your "
        "profile. It is an information tool, not a government agency.",
    ),
    (
        "How do I create an account or sign in?",
        ("create an account", "register", "sign up", "sign in", "log in"),
        "Choose Register to create an account with your name, email, and "
        "password. Use Login later with the same email and password.",
    ),
    (
        "How does SchemeMate find matching schemes?",
        (
            "matching schemes",
            "find schemes",
            "scheme matching",
            "eligibility matching",
            "how does matching work",
        ),
        "After you choose a profile type and provide the requested details, "
        "SchemeMate compares available scheme records with supported criteria "
        "such as role, state, age, income, category, or education. Matches are "
        "only suggestions; verify every requirement on the official scheme site.",
    ),
    (
        "How do I save a scheme?",
        ("save a scheme", "save this scheme", "save schemes"),
        "Sign in, open a scheme's details, and select Save this scheme. You "
        "can remove it later from your saved-schemes list.",
    ),
    (
        "Where can I see my saved schemes?",
        ("saved schemes", "see my saved", "view my saved"),
        "Select the profile icon and choose Saved schemes. Your saved list is "
        "linked to your signed-in account.",
    ),
    (
        "Can I apply for schemes through SchemeMate?",
        (
            "apply for schemes",
            "apply for a scheme",
            "apply through schememate",
            "where do i apply",
        ),
        "SchemeMate helps you discover schemes and view application information. "
        "Apply through the official portal or channel linked on the scheme details "
        "page, and confirm the current requirements there.",
    ),
    (
        "What profile information should I provide?",
        ("profile information", "profile details", "what details do i provide"),
        "Provide only the details requested on your selected profile form. Do not "
        "enter passwords, Aadhaar numbers, bank details, or other sensitive "
        "information in the chatbot.",
    ),
    (
        "Are my chat messages saved?",
        ("chat messages saved", "are my messages saved", "chat privacy"),
        "SchemeMate does not save chatbot conversations. When Gemini is enabled, "
        "your chat message and a short list of matching scheme records are sent "
        "to Google to generate a reply. Avoid sharing sensitive personal details.",
    ),
)
SCHEME_TARGET_ROLES = (
    "Student",
    "Farmer",
    "Job Seeker",
    "Entrepreneur",
    "Woman",
    "Senior Citizen",
    "Person with Disability",
    "Other",
)
SCHEME_ILLUSTRATIONS = {
    "student": ("student.svg", "A student holding and reading a book"),
    "farmer": ("farmer.svg", "A farmer standing beside crops"),
    "job seeker": ("job-seeker.svg", "A job seeker holding a resume"),
    "entrepreneur": ("entrepreneur.svg", "A small business owner at a shop"),
    "woman": ("woman.svg", "A woman reviewing a document"),
    "senior citizen": ("senior-citizen.svg", "A senior citizen using a walking cane"),
    "person with disability": (
        "person-with-disability.svg",
        "A wheelchair user",
    ),
    "other": ("other.svg", "Community members standing together"),
}


def configured_admin_emails():
    return {
        email.strip().casefold()
        for setting in (
            os.environ.get("ADMIN_EMAILS", ""),
            os.environ.get("ADMIN_EMAIL", ""),
        )
        for email in setting.split(",")
        if email.strip()
    }


def current_session_is_admin():
    email = session.get("user_email")
    return bool(
        session.get("user_id")
        and isinstance(email, str)
        and email.strip().casefold() in configured_admin_emails()
    )


@app.context_processor
def inject_admin_shortcut():
    return {"show_admin_shortcut": current_session_is_admin()}


def current_user_is_admin(cursor):
    user_id = session.get("user_id")
    admin_emails = configured_admin_emails()
    if not user_id or not admin_emails:
        return False

    cursor.execute("SELECT email FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    return bool(
        user
        and user.get("email")
        and user["email"].strip().casefold() in admin_emails
    )


def get_admin_csrf_token():
    token = session.get("admin_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


def valid_admin_csrf_token():
    expected = session.get("admin_csrf_token")
    submitted = request.form.get("csrf_token", "")
    return bool(
        isinstance(expected, str)
        and submitted
        and hmac.compare_digest(expected, submitted)
    )


@app.context_processor
def inject_admin_csrf_token():
    return {"admin_csrf_token": get_admin_csrf_token}


@app.context_processor
def inject_chatbot_faq_questions():
    return {"chatbot_faq_questions": [faq[0] for faq in WEBSITE_FAQS]}


def get_scheme_illustration(target_role):
    filename, alt = SCHEME_ILLUSTRATIONS.get(
        (target_role or "").casefold(),
        SCHEME_ILLUSTRATIONS["other"],
    )
    return {"filename": f"images/schemes/{filename}", "alt": alt}


def add_saved_scheme_status(cursor, schemes, user_id):
    for scheme in schemes:
        scheme["is_saved"] = False

    if not user_id or not schemes:
        return True

    try:
        cursor.execute(
            "SELECT scheme_id FROM saved_schemes WHERE user_id = %s",
            (user_id,)
        )
    except MySQLDatabaseError as error:
        if error.errno != 1146:
            raise
        app.logger.warning(
            "Saved-schemes table is missing; listing schemes without save controls."
        )
        return False

    saved_ids = {row["scheme_id"] for row in cursor.fetchall()}
    for scheme in schemes:
        scheme["is_saved"] = scheme["scheme_id"] in saved_ids
    return True


def safe_local_return_to(default_url):
    candidate = request.form.get("return_to", "").strip()
    parsed = urlsplit(candidate)
    if (
        not candidate
        or parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or "\\" in candidate
        or any(ord(character) < 32 for character in candidate)
    ):
        return default_url
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


@app.context_processor
def inject_scheme_illustration():
    return {"scheme_illustration": get_scheme_illustration}


def get_saved_scheme_csrf_token():
    token = session.get("saved_scheme_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["saved_scheme_csrf_token"] = token
    return token


def valid_saved_scheme_csrf_token():
    expected = session.get("saved_scheme_csrf_token")
    submitted = request.form.get("csrf_token", "")
    return bool(
        isinstance(expected, str)
        and submitted
        and hmac.compare_digest(expected, submitted)
    )


@app.context_processor
def inject_saved_scheme_csrf_token():
    return {"saved_scheme_csrf_token": get_saved_scheme_csrf_token}


def get_contact_csrf_token():
    token = session.get("contact_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["contact_csrf_token"] = token
    return token


def valid_contact_csrf_token():
    expected = session.get("contact_csrf_token")
    submitted = request.form.get("csrf_token", "")
    return bool(
        isinstance(expected, str)
        and submitted
        and hmac.compare_digest(expected, submitted)
    )


@app.context_processor
def inject_contact_csrf_token():
    return {"contact_csrf_token": get_contact_csrf_token}


def parse_admin_scheme_form(form):
    text_fields = (
        "scheme_name",
        "description",
        "target_role",
        "state",
        "category",
        "education_level",
        "benefit",
        "documents",
        "application_process",
        "official_link",
    )
    values = {field: form.get(field, "").strip() for field in text_fields}
    required_fields = (
        "scheme_name",
        "description",
        "target_role",
        "state",
        "benefit",
        "documents",
        "application_process",
        "official_link",
    )
    if any(not values[field] for field in required_fields):
        return None, "Complete all required fields."
    if values["target_role"] not in SCHEME_TARGET_ROLES:
        return None, "Select a valid target role."
    if not values["category"]:
        values["category"] = "All"
    if not values["education_level"]:
        values["education_level"] = "All"

    max_lengths = {
        "scheme_name": 255,
        "target_role": 50,
        "state": 100,
        "category": 100,
        "education_level": 100,
    }
    if any(len(values[field]) > limit for field, limit in max_lengths.items()):
        return None, "One or more fields exceed the allowed length."
    if any(
        len(values[field]) > 10000
        for field in (
            "description",
            "benefit",
            "documents",
            "application_process",
        )
    ):
        return None, "Scheme descriptions must be 10,000 characters or fewer."

    try:
        link = urlsplit(values["official_link"])
    except ValueError:
        return None, "Enter a valid HTTPS official scheme URL."
    if link.scheme != "https" or not link.hostname or link.username or link.password:
        return None, "Enter a valid HTTPS official scheme URL."

    numbers = {}
    for field in ("min_age", "max_age"):
        raw_value = form.get(field, "").strip()
        if not raw_value:
            numbers[field] = None
            continue
        try:
            age = int(raw_value)
        except ValueError:
            return None, "Age limits must be whole numbers."
        if age < 0 or age > 130:
            return None, "Age limits must be between 0 and 130."
        numbers[field] = age
    if (
        numbers["min_age"] is not None
        and numbers["max_age"] is not None
        and numbers["min_age"] > numbers["max_age"]
    ):
        return None, "Minimum age cannot exceed maximum age."

    raw_income = form.get("max_income", "").strip()
    if raw_income:
        try:
            max_income = Decimal(raw_income)
        except InvalidOperation:
            return None, "Enter a valid maximum income."
        if (
            not max_income.is_finite()
            or max_income < 0
            or max_income > Decimal("999999999999.99")
        ):
            return None, "Enter a valid maximum income."
    else:
        max_income = None

    values.update(numbers)
    values["max_income"] = max_income
    return values, None


def scheme_state_match_reason(scheme_state, profile_state):
    def normalize(value):
        state = " ".join((value or "").casefold().replace(".", " ").split())
        aliases = {
            "tn": "tamil nadu",
            "tamilnadu": "tamil nadu",
            "ka": "karnataka",
        }
        return aliases.get(state, state)

    normalized_scheme_state = normalize(scheme_state)
    if normalized_scheme_state in {"", "all", "all india", "india"}:
        return "The scheme is available across India."

    if normalized_scheme_state == normalize(profile_state):
        return "Your state matches the scheme."

    return None


def find_website_faq_reply(question):
    normalized = " ".join(re.findall(r"[a-z0-9]+", question.casefold()))
    for _, triggers, answer in WEBSITE_FAQS:
        if any(trigger in normalized for trigger in triggers):
            return answer
    return None


def build_website_faq_fallback():
    questions = "; ".join(faq[0] for faq in WEBSITE_FAQS)
    return (
        "The AI assistant is temporarily unavailable. I can still answer "
        "these SchemeMate questions: " + questions
    )


def get_chat_scheme_context(question):
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT scheme_name, target_role, state, description, min_age,
                   max_age, max_income, category, education_level,
                   benefit, official_link
            FROM schemes
            ORDER BY target_role, scheme_name
            """
        )
        schemes = cursor.fetchall()
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()

    ignored_terms = {
        "the", "for", "and", "with", "what", "are", "how", "can", "you",
        "does", "from", "about", "scheme", "schemes", "find", "tell",
        "show", "please", "in", "on", "my", "of", "is", "this", "that",
        "your", "eligible", "available", "get",
    }
    terms = {
        term for term in re.findall(r"[a-z0-9]+", question.casefold())
        if len(term) > 2 and term not in ignored_terms
    }
    role_aliases = {
        "women": "woman",
        "female": "woman",
        "farmers": "farmer",
        "students": "student",
        "elderly": "senior citizen",
        "seniors": "senior citizen",
        "disabled": "person with disability",
        "disability": "person with disability",
        "business": "entrepreneur",
        "businesses": "entrepreneur",
        "job": "job seeker",
        "jobs": "job seeker",
        "employment": "job seeker",
    }
    for alias, role in role_aliases.items():
        if alias in terms:
            terms.update(role.split())

    ranked_schemes = []
    for scheme in schemes:
        searchable_text = " ".join(
            str(scheme.get(field) or "")
            for field in ("scheme_name", "target_role", "state", "description", "benefit")
        ).casefold()
        searchable_terms = set(re.findall(r"[a-z0-9]+", searchable_text))
        score = len(terms.intersection(searchable_terms))
        if score:
            ranked_schemes.append((score, scheme))

    if ranked_schemes:
        ranked_schemes.sort(
            key=lambda item: (-item[0], item[1]["target_role"], item[1]["scheme_name"])
        )
        selected = [scheme for _, scheme in ranked_schemes[:8]]
    else:
        selected = schemes[:8]

    context = []
    sources = []
    for scheme in selected:
        record = {
            "name": scheme["scheme_name"],
            "role": scheme["target_role"],
            "state": scheme.get("state") or "Not specified",
            "description": scheme.get("description") or "",
            "min_age": scheme.get("min_age"),
            "max_age": scheme.get("max_age"),
            "max_income": str(scheme["max_income"]) if scheme.get("max_income") is not None else None,
            "category": scheme.get("category") or "Not specified",
            "education_level": scheme.get("education_level") or "Not specified",
            "benefit": scheme.get("benefit") or "",
            "official_link": scheme.get("official_link") or "",
        }
        context.append(record)
        link = record["official_link"]
        if link.startswith("https://"):
            sources.append({"name": record["name"], "url": link})

    return context, sources


def build_local_chat_reply(question, schemes):
    if not schemes:
        return (
            "I couldn't find a matching scheme in the current SchemeMate list. "
            "Try asking by category, such as student, farmer, woman, senior citizen, "
            "person with disability, entrepreneur, or job seeker."
        )

    reply_lines = [
        "These SchemeMate records may be relevant based on your question. "
        "They are not a confirmation of eligibility:"
    ]
    for scheme in schemes[:5]:
        description = scheme["description"].strip()
        if len(description) > 240:
            description = description[:237].rsplit(" ", 1)[0] + "..."
        reply_lines.append(
            f"- {scheme['name']} ({scheme['role']}, {scheme['state']}): "
            f"{description or 'Check the official scheme page for details.'}"
        )
    reply_lines.append(
        "Review the linked official source for current rules and application details."
    )
    return "\n\n".join(reply_lines)


def ask_gemini(messages, scheme_context):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
        raise ValueError("Invalid Gemini model name.")

    system_instruction = (
        "You are SchemeMate's government-scheme information assistant. "
        "Answer using only the supplied SchemeMate records. Do not invent schemes, "
        "eligibility rules, benefit amounts, deadlines, or application steps. "
        "If the records do not answer something, say so and direct the user to the "
        "official source. Explain that results are indicative, not a final eligibility "
        "decision. Do not ask for Aadhaar numbers, passwords, bank details, or other "
        "sensitive personal data. Keep the answer concise. Scheme records: "
        + json.dumps(scheme_context, ensure_ascii=True)
    )
    contents = [
        {
            "role": "model" if message["role"] == "assistant" else "user",
            "parts": [{"text": message["content"]}],
        }
        for message in messages
    ]
    body = json.dumps({
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
    }).encode("utf-8")
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    gemini_request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(gemini_request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        app.logger.warning("Gemini request failed with HTTP %s", error.code)
        raise RuntimeError("The AI assistant is temporarily unavailable.") from None
    except URLError:
        app.logger.warning("Gemini request could not reach the service.")
        raise RuntimeError("The AI assistant is temporarily unavailable.") from None

    try:
        parts = result["candidates"][0]["content"]["parts"]
        answer = "\n".join(part["text"] for part in parts if "text" in part).strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("The AI assistant returned an unreadable response.") from None
    if not answer:
        raise RuntimeError("The AI assistant returned an empty response.")
    return answer


@app.route("/api/chat", methods=["POST"])
def chat():
    if not request.is_json:
        return jsonify(error="Send the chat request as JSON."), 400
    if request.content_length is not None and request.content_length > 24576:
        return jsonify(error="The chat request is too large."), 413

    payload = request.get_json(silent=True)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Enter a message to continue."), 400
    if len(messages) > CHAT_MAX_HISTORY:
        return jsonify(error="Start a new chat to continue."), 400
    valid_messages = []
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"user", "assistant"}
            or not isinstance(message.get("content"), str)
        ):
            return jsonify(error="The chat message format is invalid."), 400
        content = message["content"].strip()
        if not content or len(content) > CHAT_MAX_MESSAGE_LENGTH:
            return jsonify(error="Messages must be between 1 and 1200 characters."), 400
        valid_messages.append({"role": message["role"], "content": content})

    if valid_messages[-1]["role"] != "user":
        return jsonify(error="Send a user message to continue."), 400

    now = time.monotonic()
    request_times = chat_requests_by_ip[request.remote_addr or "unknown"]
    while request_times and now - request_times[0] >= CHAT_RATE_WINDOW_SECONDS:
        request_times.popleft()
    if len(request_times) >= CHAT_RATE_LIMIT:
        return jsonify(error="Please wait a minute before sending more messages."), 429
    request_times.append(now)

    faq_reply = find_website_faq_reply(valid_messages[-1]["content"])
    if faq_reply:
        return jsonify(reply=faq_reply, sources=[], mode="faq")

    try:
        scheme_context, sources = get_chat_scheme_context(valid_messages[-1]["content"])
        answer = ask_gemini(valid_messages, scheme_context)
        mode = "gemini" if answer is not None else "database"
        if answer is None:
            answer = build_local_chat_reply(valid_messages[-1]["content"], scheme_context)
        return jsonify(reply=answer, sources=sources, mode=mode)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        app.logger.warning("Gemini unavailable; serving manual FAQ fallback: %s", error)
        return jsonify(
            reply=build_website_faq_fallback(),
            sources=[],
            mode="faq",
        )
    except Exception:
        app.logger.exception("SchemeMate chatbot request failed")
        return jsonify(error="Unable to load scheme information right now."), 500


# ---------------- HOME ----------------

@app.route("/")
def home():
    return render_template("index.html")


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        # Check passwords
        if password != confirm_password:
            return "Passwords do not match"

        # Hash password
        hashed_password = generate_password_hash(password)

        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            query = """
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s)
            """

            cursor.execute(
                query,
                (name, email, hashed_password)
            )

            connection.commit()

            # Get the newly created user's ID
            user_id = cursor.lastrowid

            # Store user ID in session
            session["user_id"] = user_id
            session["user_name"] = name
            session["user_email"] = email

            return redirect(url_for("roles"))

        except Exception as e:
            if connection:
                connection.rollback()

            return f"Registration error: {e}"

        finally:
            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("register.html")
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor(dictionary=True)

            query = """
            SELECT user_id, name, email, password
            FROM users
            WHERE email = %s
            """

            cursor.execute(query, (email,))
            user = cursor.fetchone()

            if user is None:
                return "Account not found. Please register first."

            if not check_password_hash(user["password"], password):
                return "Incorrect password."

            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

            return redirect(url_for("roles"))

        except Exception as e:
            return f"Login error: {e}"

        finally:
            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("login.html")    


# ---------------- ROLE SELECTION ----------------

@app.route("/roles", methods=["GET", "POST"])
def roles():

    if request.method == "POST":

        selected_roles = request.form.getlist("roles")

        # Make sure user is registered
        user_id = session.get("user_id")

        if not user_id:
            return redirect(url_for("register"))

        if not selected_roles:
            return "Please select at least one role."
        if len(selected_roles) != 1 or selected_roles[0] not in SCHEME_TARGET_ROLES:
            return "Please select exactly one valid role."

        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute(
                "DELETE FROM user_roles WHERE user_id = %s",
                (user_id,)
            )

            # Find role IDs from role names
            for role_name in selected_roles:

                cursor.execute(
                    "SELECT role_id FROM roles WHERE role_name = %s",
                    (role_name,)
                )

                result = cursor.fetchone()

                if result:
                    role_id = result[0]

                    cursor.execute(
                        """
                        INSERT IGNORE INTO user_roles (user_id, role_id)
                        VALUES (%s, %s)
                        """,
                        (user_id, role_id)
                    )

            connection.commit()
            if "Student" in selected_roles:
                return redirect(url_for("student_profile"))
            if "Farmer" in selected_roles:
                return redirect(url_for("farmer_profile")) 
            if "Job Seeker" in selected_roles:
                return redirect(url_for("jobseeker_profile"))       
            if "Woman" in selected_roles:
                return redirect(url_for("category_profile", category="woman"))
            if "Senior Citizen" in selected_roles:
                return redirect(url_for("category_profile", category="senior-citizen"))
            if "Person with Disability" in selected_roles:
                return redirect(url_for("category_profile", category="person-with-disability"))
            if "Entrepreneur" in selected_roles:
                return redirect(url_for("category_profile", category="entrepreneur"))
            if "Other" in selected_roles:
                return redirect(url_for("category_profile", category="other"))

            return "Roles saved successfully!"

        except Exception as e:

            if connection:
                connection.rollback()

            return f"Role error: {e}"

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("roles.html")


@app.route("/admin/schemes")
def admin_schemes():
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        if not current_user_is_admin(cursor):
            return "Admin access required.", 403

        cursor.execute(
            """
            SELECT scheme_id, scheme_name, target_role, state
            FROM schemes
            ORDER BY target_role, scheme_name
            """
        )
        return render_template("admin_schemes.html", schemes=cursor.fetchall())
    except Exception:
        app.logger.exception("Failed to load the admin scheme list")
        return "Unable to load schemes right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/admin/schemes/new", methods=["GET", "POST"])
def admin_scheme_new():
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        if not current_user_is_admin(cursor):
            return "Admin access required.", 403

        scheme = {}
        if request.method == "POST":
            if not valid_admin_csrf_token():
                return "Invalid form token. Reload the page and try again.", 400
            scheme, error = parse_admin_scheme_form(request.form)
            if error:
                return render_template(
                    "admin_scheme_form.html",
                    scheme=request.form,
                    target_roles=SCHEME_TARGET_ROLES,
                    form_title="Add a scheme",
                    submit_label="Add scheme",
                    form_action=url_for("admin_scheme_new"),
                    error=error,
                ), 400

            cursor.execute(
                """
                INSERT INTO schemes (
                    scheme_name, description, target_role, state, min_age,
                    max_age, max_income, category, education_level, benefit,
                    documents, application_process, official_link
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                tuple(scheme[field] for field in (
                    "scheme_name", "description", "target_role", "state",
                    "min_age", "max_age", "max_income", "category",
                    "education_level", "benefit", "documents",
                    "application_process", "official_link",
                )),
            )
            connection.commit()
            return redirect(url_for("admin_schemes"))

        return render_template(
            "admin_scheme_form.html",
            scheme=scheme,
            target_roles=SCHEME_TARGET_ROLES,
            form_title="Add a scheme",
            submit_label="Add scheme",
            form_action=url_for("admin_scheme_new"),
            error=None,
        )
    except Exception:
        if connection is not None:
            connection.rollback()
        app.logger.exception("Failed to create a scheme")
        return "Unable to save the scheme right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/admin/schemes/<int:scheme_id>/edit", methods=["GET", "POST"])
def admin_scheme_edit(scheme_id):
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        if not current_user_is_admin(cursor):
            return "Admin access required.", 403

        cursor.execute("SELECT * FROM schemes WHERE scheme_id = %s", (scheme_id,))
        scheme = cursor.fetchone()
        if not scheme:
            return "Scheme not found.", 404

        error = None
        if request.method == "POST":
            if not valid_admin_csrf_token():
                return "Invalid form token. Reload the page and try again.", 400
            updated_scheme, error = parse_admin_scheme_form(request.form)
            if not error:
                cursor.execute(
                    """
                    UPDATE schemes
                    SET scheme_name = %s, description = %s, target_role = %s,
                        state = %s, min_age = %s, max_age = %s, max_income = %s,
                        category = %s, education_level = %s, benefit = %s,
                        documents = %s, application_process = %s, official_link = %s
                    WHERE scheme_id = %s
                    """,
                    tuple(updated_scheme[field] for field in (
                        "scheme_name", "description", "target_role", "state",
                        "min_age", "max_age", "max_income", "category",
                        "education_level", "benefit", "documents",
                        "application_process", "official_link",
                    )) + (scheme_id,),
                )
                connection.commit()
                return redirect(url_for("admin_schemes"))
            scheme = request.form

        return render_template(
            "admin_scheme_form.html",
            scheme=scheme,
            target_roles=SCHEME_TARGET_ROLES,
            form_title="Edit scheme",
            submit_label="Save changes",
            form_action=url_for("admin_scheme_edit", scheme_id=scheme_id),
            error=error,
        ), 400 if error else 200
    except Exception:
        if connection is not None:
            connection.rollback()
        app.logger.exception("Failed to edit scheme %s", scheme_id)
        return "Unable to save the scheme right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/admin/schemes/<int:scheme_id>/delete", methods=["POST"])
def admin_scheme_delete(scheme_id):
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        if not current_user_is_admin(cursor):
            return "Admin access required.", 403
        if not valid_admin_csrf_token():
            return "Invalid form token. Reload the page and try again.", 400

        cursor.execute("DELETE FROM schemes WHERE scheme_id = %s", (scheme_id,))
        if cursor.rowcount == 0:
            return "Scheme not found.", 404
        connection.commit()
        return redirect(url_for("admin_schemes"))
    except Exception:
        if connection is not None:
            connection.rollback()
        app.logger.exception("Failed to delete scheme %s", scheme_id)
        return "Unable to delete the scheme right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/schemes")
def all_schemes():
    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT scheme_id, scheme_name, target_role, state, description,
                   benefit, official_link
            FROM schemes
            ORDER BY target_role, scheme_name
            """
        )
        schemes = cursor.fetchall()
        save_available = add_saved_scheme_status(
            cursor,
            schemes,
            session.get("user_id"),
        )
        return render_template(
            "all_schemes.html",
            schemes=schemes,
            scheme_save_available=save_available,
        )
    except Exception:
        app.logger.exception("Failed to load all schemes")
        return "Unable to load schemes right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "GET":
        return render_template("contact.html", form_data={})

    if request.content_length is not None and request.content_length > 16384:
        return render_template(
            "contact.html",
            form_data={},
            error="The complaint form is too large.",
        ), 413

    form_data = {
        field: request.form.get(field, "").strip()
        for field in ("name", "email", "address", "issue")
    }
    if not valid_contact_csrf_token():
        return render_template(
            "contact.html",
            form_data=form_data,
            error="Your form session expired. Reload the page and try again.",
        ), 400

    name = form_data["name"]
    email = form_data["email"]
    address = form_data["address"]
    issue = form_data["issue"]
    if (
        not name
        or len(name) > 120
        or not is_valid_email(email)
        or not address
        or len(address) > 1000
        or not issue
        or len(issue) > 5000
        or request.form.get("consent") != "yes"
    ):
        return render_template(
            "contact.html",
            form_data=form_data,
            error=(
                "Enter a valid name and email, provide your address and issue, "
                "and confirm the privacy notice."
            ),
        ), 400

    now = time.monotonic()
    request_times = complaint_requests_by_ip[request.remote_addr or "unknown"]
    while request_times and now - request_times[0] >= COMPLAINT_RATE_WINDOW_SECONDS:
        request_times.popleft()
    if len(request_times) >= COMPLAINT_RATE_LIMIT:
        return render_template(
            "contact.html",
            form_data=form_data,
            error="Please wait before submitting another complaint.",
        ), 429
    request_times.append(now)

    try:
        send_complaint_email(name, email, address, issue)
    except RuntimeError as error:
        app.logger.warning("Complaint email is not configured: %s", error)
    except Exception:
        app.logger.exception("Failed to send a SchemeMate complaint")
    else:
        flash("Your complaint was sent successfully.", "success")
        return redirect(url_for("contact"))

    recipient = os.environ.get(
        "COMPLAINT_RECIPIENT",
        "brundagr17@gmail.com",
    ).strip()
    if not is_valid_email(recipient):
        recipient = "brundagr17@gmail.com"
    email_body = (
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Address: {address}\n\n"
        f"Issue:\n{issue}\n"
    )
    fallback_email_url = (
        f"mailto:{recipient}?"
        + urlencode({
            "subject": "SchemeMate complaint report",
            "body": email_body,
        })
    )
    return render_template(
        "contact.html",
        form_data=form_data,
        error=(
            "We could not send the complaint automatically. Use the button "
            "below to open an email with your report ready to send."
        ),
        fallback_email_url=fallback_email_url,
    ), 503


def is_valid_email(value):
    return bool(
        len(value) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value)
    )


def send_complaint_email(name, email, address, issue):
    smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_password = "".join(os.environ.get("SMTP_APP_PASSWORD", "").split())
    recipient = os.environ.get(
        "COMPLAINT_RECIPIENT",
        "brundagr17@gmail.com",
    ).strip()
    if (
        not is_valid_email(smtp_username)
        or not smtp_password
        or not is_valid_email(recipient)
    ):
        raise RuntimeError("Missing or invalid Gmail SMTP configuration.")

    message = EmailMessage()
    message["Subject"] = "SchemeMate complaint report"
    message["From"] = smtp_username
    message["To"] = recipient
    message["Reply-To"] = email
    message.set_content(
        "A complaint was submitted through SchemeMate.\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Address: {address}\n\n"
        "Issue:\n"
        f"{issue}\n"
    )

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_username, smtp_password)
        refused_recipients = smtp.send_message(message)
    if refused_recipients:
        raise smtplib.SMTPRecipientsRefused(refused_recipients)

@app.route("/relevant-schemes")
@app.route("/relevant-schemes")
def relevant_schemes():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Get the latest student profile
        cursor.execute("""
            SELECT *
            FROM student_profiles
            WHERE user_id = %s
            ORDER BY profile_id DESC
            LIMIT 1
        """, (user_id,))

        student = cursor.fetchone()

        if not student:
            return "Student profile not found."

        # Get student schemes
        cursor.execute("""
            SELECT *
            FROM schemes
            WHERE target_role = 'Student'
        """)

        schemes = cursor.fetchall()

        matched_schemes = []

        for scheme in schemes:

            eligible = True
            reasons = []

            state_reason = scheme_state_match_reason(
                scheme["state"], student["state"]
            )
            if state_reason is None:
                eligible = False
            else:
                reasons.append(state_reason)

            # -------------------------
            # Income check
            # -------------------------
            if scheme["max_income"] is not None:

                if student["family_income"] > scheme["max_income"]:
                    eligible = False
                else:
                    reasons.append(
                        "Your family income is within the specified limit."
                    )

            # -------------------------
            # Age check
            # -------------------------
            if scheme["min_age"] is not None:

                if student["age"] < scheme["min_age"]:
                    eligible = False
                else:
                    reasons.append(
                        "Your age satisfies the minimum age requirement."
                    )

            if scheme["max_age"] is not None:

                if student["age"] > scheme["max_age"]:
                    eligible = False
                else:
                    reasons.append(
                        "Your age is within the maximum age requirement."
                    )

            # -------------------------
            # Category check
            # -------------------------
            if scheme["category"] and scheme["category"] != "All":

                allowed_categories = [
                    category.strip()
                    for category in scheme["category"].split("/")
                ]

                if student["category"] not in allowed_categories:
                    eligible = False
                else:
                    reasons.append(
                        "Your category matches the scheme."
                    )

            else:
                reasons.append(
                    "The scheme is open to all categories."
                )

            # -------------------------
            # Education check
            # -------------------------
            education = scheme["education_level"]

            if education and education != "All":

                if education == "Undergraduate":

                    if student["education_level"] != "Undergraduate":
                        eligible = False
                    else:
                        reasons.append(
                            "Your education level matches the scheme."
                        )

                elif education == "Postgraduate":

                    if student["education_level"] != "Postgraduate":
                        eligible = False
                    else:
                        reasons.append(
                            "Your education level matches the scheme."
                        )

                elif education == "Post-Matric":

                    if student["education_level"] not in [
                        "Undergraduate",
                        "Postgraduate",
                        "Diploma"
                    ]:
                        eligible = False
                    else:
                        reasons.append(
                            "Your education level matches the scheme."
                        )

            # -------------------------
            # Add matching scheme
            # -------------------------
            if eligible:

                scheme["status"] = "Likely Eligible"
                scheme["reasons"] = reasons

                matched_schemes.append(scheme)

        save_available = add_saved_scheme_status(cursor, matched_schemes, user_id)
        return render_template(
            "relevant_schemes.html",
            schemes=matched_schemes,
            scheme_save_available=save_available,
        )

    except Exception as e:
        return f"Eligibility error: {e}"

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close() 

@app.route("/farmer-schemes")
def farmer_schemes():
    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        # Get latest farmer profile
        cursor.execute("""
            SELECT *
            FROM farmer_profiles
            WHERE user_id = %s
            ORDER BY profile_id DESC
            LIMIT 1
        """, (user_id,))

        farmer = cursor.fetchone()

        if not farmer:
            return "Farmer profile not found."

        # Get Farmer schemes
        cursor.execute("""
            SELECT *
            FROM schemes
            WHERE target_role = 'Farmer'
        """)

        schemes = cursor.fetchall()

        matched_schemes = []

        for scheme in schemes:

            eligible = True
            reasons = []

            state_reason = scheme_state_match_reason(
                scheme["state"], farmer["state"]
            )
            if state_reason is None:
                eligible = False
            else:
                reasons.append(state_reason)

            # Age check
            if scheme["min_age"] is not None:

                if farmer["age"] < scheme["min_age"]:
                    eligible = False
                else:
                    reasons.append(
                        "Your age satisfies the minimum age requirement."
                    )

            if scheme["max_age"] is not None:

                if farmer["age"] > scheme["max_age"]:
                    eligible = False
                else:
                    reasons.append(
                        "Your age is within the required range."
                    )

            # Category check
            if scheme["category"] and scheme["category"] != "All":

                allowed_categories = [
                    category.strip()
                    for category in scheme["category"].split("/")
                ]

                if farmer["category"] not in allowed_categories:
                    eligible = False
                else:
                    reasons.append(
                        "Your category matches the scheme."
                    )

            else:
                reasons.append(
                    "The scheme is open to all categories."
                )

            # Land ownership
            if farmer["land_ownership"]:
                reasons.append(
                    "Your land ownership information has been provided."
                )

            # Farming information
            if farmer["farming_type"]:
                reasons.append(
                    "Your farming details match the farmer category."
                )

            if eligible:

                scheme["status"] = "Likely Eligible"
                scheme["reasons"] = reasons

                matched_schemes.append(scheme)

        save_available = add_saved_scheme_status(cursor, matched_schemes, user_id)
        return render_template(
            "farmer_schemes.html",
            schemes=matched_schemes,
            scheme_save_available=save_available,
        )

    except Exception as e:
        return f"Farmer eligibility error: {e}"

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()            

@app.route("/scheme/<int:scheme_id>")
def scheme_details(scheme_id):

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM schemes
            WHERE scheme_id = %s
        """, (scheme_id,))

        scheme = cursor.fetchone()

        if not scheme:
            return "Scheme not found.", 404

        is_saved = False
        save_available = True
        if session.get("user_id"):
            try:
                cursor.execute(
                    """
                    SELECT 1
                    FROM saved_schemes
                    WHERE user_id = %s AND scheme_id = %s
                    """,
                    (session["user_id"], scheme_id)
                )
                is_saved = cursor.fetchone() is not None
            except MySQLDatabaseError as error:
                if error.errno != 1146:
                    raise
                app.logger.warning(
                    "Saved-schemes table is missing; showing scheme %s without save controls.",
                    scheme_id,
                )
                save_available = False

        result_routes = {
            "Student": ("relevant_schemes", None),
            "Farmer": ("farmer_schemes", None),
            "Job Seeker": ("jobseeker_schemes", None),
            "Woman": ("category_schemes", "woman"),
            "Senior Citizen": ("category_schemes", "senior-citizen"),
            "Person with Disability": (
                "category_schemes",
                "person-with-disability"
            ),
            "Entrepreneur": ("category_schemes", "entrepreneur"),
            "Other": ("category_schemes", "other"),
        }
        endpoint, category = result_routes.get(
            scheme["target_role"],
            ("home", None)
        )
        return_url = url_for(endpoint, category=category) if category else url_for(endpoint)
        if request.args.get("source") == "all":
            return_url = url_for("all_schemes")
        elif request.args.get("source") == "saved":
            return_url = url_for("saved_schemes")

        return render_template(
            "scheme_details.html",
            scheme=scheme,
            return_url=return_url,
            is_saved=is_saved,
            save_available=save_available,
        )

    except Exception:
        app.logger.exception("Failed to load scheme details")
        return "Unable to load scheme details right now.", 500

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()               


@app.route("/account")
def account():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT u.name, u.email, r.role_name
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.user_id
            LEFT JOIN roles r ON r.role_id = ur.role_id
            WHERE u.user_id = %s
            ORDER BY r.role_name
            """,
            (user_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            session.clear()
            return redirect(url_for("login"))

        account_details = {"name": rows[0]["name"], "email": rows[0]["email"]}
        roles = [row["role_name"] for row in rows if row["role_name"]]
        saved_count = 0
        saved_schemes_available = True
        try:
            cursor.execute(
                "SELECT COUNT(*) AS saved_count FROM saved_schemes WHERE user_id = %s",
                (user_id,)
            )
            saved_count = cursor.fetchone()["saved_count"]
        except MySQLDatabaseError as error:
            if error.errno != 1146:
                raise
            app.logger.warning(
                "Saved-schemes table is missing; loading account without saved count."
            )
            saved_schemes_available = False

        return render_template(
            "account.html",
            account=account_details,
            roles=roles,
            saved_count=saved_count,
            saved_schemes_available=saved_schemes_available,
        )
    except Exception:
        app.logger.exception("Failed to load account details")
        return "Unable to load your account right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/saved-schemes")
def saved_schemes():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.scheme_id, s.scheme_name, s.target_role, s.state,
                   s.description, s.official_link, ss.saved_at
            FROM saved_schemes ss
            JOIN schemes s ON s.scheme_id = ss.scheme_id
            WHERE ss.user_id = %s
            ORDER BY ss.saved_at DESC, s.scheme_name
            """,
            (user_id,)
        )
        return render_template("saved_schemes.html", schemes=cursor.fetchall())
    except Exception:
        app.logger.exception("Failed to load saved schemes")
        return "Unable to load your saved schemes right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/scheme/<int:scheme_id>/save", methods=["POST"])
def save_scheme(scheme_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))
    if not valid_saved_scheme_csrf_token():
        return "Invalid request token.", 400

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT scheme_id FROM schemes WHERE scheme_id = %s",
            (scheme_id,)
        )
        if cursor.fetchone() is None:
            return "Scheme not found.", 404

        cursor.execute(
            """
            INSERT INTO saved_schemes (user_id, scheme_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE saved_at = CURRENT_TIMESTAMP
            """,
            (user_id, scheme_id)
        )
        connection.commit()
        return redirect(
            safe_local_return_to(
                url_for("scheme_details", scheme_id=scheme_id)
            )
        )
    except Exception:
        if connection is not None:
            connection.rollback()
        app.logger.exception("Failed to save scheme %s", scheme_id)
        return "Unable to save this scheme right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/scheme/<int:scheme_id>/unsave", methods=["POST"])
def unsave_scheme(scheme_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))
    if not valid_saved_scheme_csrf_token():
        return "Invalid request token.", 400

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute(
            """
            DELETE FROM saved_schemes
            WHERE user_id = %s AND scheme_id = %s
            """,
            (user_id, scheme_id)
        )
        connection.commit()
        return redirect(safe_local_return_to(url_for("saved_schemes")))
    except Exception:
        if connection is not None:
            connection.rollback()
        app.logger.exception("Failed to remove saved scheme %s", scheme_id)
        return "Unable to remove this saved scheme right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/student-profile", methods=["GET", "POST"])
def student_profile():

    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":

        age = request.form["age"]
        state = request.form["state"]
        education_level = request.form["education_level"]
        year_of_study = request.form["year_of_study"]
        family_income = request.form["family_income"]
        category = request.form["category"]
        percentage = request.form["percentage"]
        gender = request.form["gender"]

        connection = None
        cursor = None

        try:

            connection = get_connection()
            cursor = connection.cursor()

            query = """
            INSERT INTO student_profiles
            (
                user_id,
                age,
                state,
                education_level,
                year_of_study,
                family_income,
                category,
                percentage,
                gender
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (
                    user_id,
                    age,
                    state,
                    education_level,
                    year_of_study,
                    family_income,
                    category,
                    percentage,
                    gender
                )
            )

            connection.commit()

            return redirect(url_for("relevant_schemes"))

        except Exception as e:

            if connection:
                connection.rollback()

            return f"Profile error: {e}"

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("student_profile.html")  

@app.route("/farmer-profile", methods=["GET", "POST"])
def farmer_profile():

    user_id = session.get("user_id")

    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":

        age = request.form["age"]
        state = request.form["state"]
        district = request.form["district"]
        land_ownership = request.form["land_ownership"]
        land_size = request.form["land_size"]
        farming_type = request.form["farming_type"]
        crop_grown = request.form["crop_grown"]
        annual_income = request.form["annual_income"]
        category = request.form["category"]
        irrigation = request.form["irrigation"]

        connection = None
        cursor = None

        try:

            connection = get_connection()
            cursor = connection.cursor()

            query = """
            INSERT INTO farmer_profiles
            (
                user_id,
                age,
                state,
                district,
                land_ownership,
                land_size,
                farming_type,
                crop_grown,
                annual_income,
                category,
                irrigation
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (
                    user_id,
                    age,
                    state,
                    district,
                    land_ownership,
                    land_size,
                    farming_type,
                    crop_grown,
                    annual_income,
                    category,
                    irrigation
                )
            )

            connection.commit()

            return redirect(url_for("farmer_schemes"))

        except Exception as e:

            if connection:
                connection.rollback()

            return f"Farmer profile error: {e}"

        finally:

            if cursor:
                cursor.close()

            if connection:
                connection.close()

    return render_template("farmer_profile.html")

@app.route('/jobseeker_profile', methods=['GET', 'POST'])
def jobseeker_profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if request.method == 'POST':
        age = request.form.get('age', type=int)
        state = request.form.get('state', '').strip()
        district = request.form.get('district', '').strip()
        qualification = request.form.get('qualification', '').strip()
        skills = request.form.get('skills', '').strip()
        employment_status = request.form.get('employment_status', '').strip()
        experience = request.form.get('experience', '').strip()
        job_type = request.form.get('job_type', '').strip()

        if (
            age is None or not 18 <= age <= 100
            or not all([
                state, district, qualification, skills,
                employment_status, experience, job_type
            ])
        ):
            return render_template(
                'jobseeker_profile.html',
                message='Please complete all fields correctly.'
            ), 400

        connection = None
        cursor = None

        try:
            connection = get_connection()
            cursor = connection.cursor()

            query = """
                INSERT INTO jobseeker_profiles
                (user_id, age, state, district, qualification, skills,
                 employment_status, experience, job_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            values = (
                user_id, age, state, district, qualification, skills,
                employment_status, experience, job_type
            )

            cursor.execute(query, values)
            connection.commit()

            return redirect(url_for("jobseeker_schemes"))

        except Exception:
            if connection is not None:
                connection.rollback()

            app.logger.exception('Failed to save Job Seeker profile')
            return render_template(
                'jobseeker_profile.html',
                message='Unable to save your profile. Please try again.'
            ), 500

        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None and connection.is_connected():
                connection.close()

    return render_template('jobseeker_profile.html')  


@app.route("/jobseeker-schemes")
def jobseeker_schemes():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT age, state, qualification
            FROM jobseeker_profiles
            WHERE user_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,)
        )
        profile = cursor.fetchone()
        if profile is None:
            return redirect(url_for("jobseeker_profile"))

        cursor.execute(
            "SELECT * FROM schemes WHERE target_role = %s",
            ("Job Seeker",)
        )
        schemes = cursor.fetchall()
        matched_schemes = []
        qualification = profile["qualification"].casefold()

        for scheme in schemes:
            eligible = True
            reasons = []

            state_reason = scheme_state_match_reason(
                scheme["state"], profile["state"]
            )
            if state_reason is None:
                eligible = False
            else:
                reasons.append(state_reason)

            if scheme["min_age"] is not None:
                if profile["age"] < scheme["min_age"]:
                    eligible = False
                else:
                    reasons.append("Your age meets the minimum requirement.")

            if scheme["max_age"] is not None:
                if profile["age"] > scheme["max_age"]:
                    eligible = False
                else:
                    reasons.append("Your age is within the required range.")

            required_education = (scheme["education_level"] or "All").casefold()
            if required_education not in {"all", "any"}:
                post_matric_qualifications = {
                    "puc", "diploma", "graduate", "postgraduate"
                }
                if required_education == "post-matric":
                    education_matches = qualification in post_matric_qualifications
                else:
                    education_matches = qualification == required_education

                if not education_matches:
                    eligible = False
                else:
                    reasons.append("Your qualification matches the scheme.")

            if eligible:
                scheme["status"] = "Potential Match"
                scheme["reasons"] = reasons
                matched_schemes.append(scheme)

        save_available = add_saved_scheme_status(cursor, matched_schemes, user_id)
        return render_template(
            "relevant_schemes.html",
            schemes=matched_schemes,
            scheme_save_available=save_available,
            match_note=(
                "These are potential matches based on the profile details "
                "provided. Check the scheme details on myScheme to confirm "
                "all eligibility conditions before applying."
            )
        )
    except Exception:
        app.logger.exception("Failed to find job-seeker schemes")
        return "Unable to load relevant schemes right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


@app.route("/profile/<category>", methods=["GET", "POST"])
def category_profile(category):
    profile_templates = {
        "woman": {
            "template": "woman_profile.html",
            "role": "Woman",
            "fields": (
                "age", "state", "district", "education_level", "occupation",
                "annual_income", "marital_status", "category"
            ),
        },
        "senior-citizen": {
            "template": "senior_citizen_profile.html",
            "role": "Senior Citizen",
            "fields": (
                "age", "state", "district", "annual_income", "pension_status",
                "living_arrangement", "category"
            ),
        },
        "person-with-disability": {
            "template": "disability_profile.html",
            "role": "Person with Disability",
            "fields": (
                "age", "state", "district", "disability_type",
                "disability_percentage", "certificate_status",
                "education_level", "annual_income"
            ),
        },
        "entrepreneur": {
            "template": "entrepreneur_profile.html",
            "role": "Entrepreneur",
            "fields": (
                "age", "state", "district", "business_type", "business_stage",
                "registration_status", "annual_turnover", "annual_income",
                "category"
            ),
        },
        "other": {
            "template": "other_profile.html",
            "role": "Other",
            "fields": (
                "age", "state", "district", "education_level", "occupation",
                "annual_income", "category", "interests"
            ),
        },
    }

    profile = profile_templates.get(category)
    if profile is None:
        return "Profile category not found.", 404

    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        values = {
            field: request.form.get(field, "").strip()
            for field in profile["fields"]
        }
        required_fields = set(profile["fields"])
        if category == "person-with-disability":
            required_fields.remove("disability_percentage")

        if any(not values[field] for field in required_fields):
            return render_template(
                profile["template"],
                message="Please complete all required fields."
            ), 400

        try:
            age = int(values["age"])
            minimum_age = 60 if category == "senior-citizen" else (
                18 if category == "entrepreneur" else 1
            )
            if not minimum_age <= age <= 120:
                raise ValueError("Age is outside the allowed range.")

            annual_income = Decimal(values["annual_income"])
            if not annual_income.is_finite() or annual_income < 0:
                raise ValueError("Income cannot be negative.")

            for amount_field in ("annual_turnover",):
                if amount_field in values:
                    amount = Decimal(values[amount_field])
                    if not amount.is_finite() or amount < 0:
                        raise ValueError("Turnover cannot be negative.")

            if values.get("disability_percentage"):
                percentage = int(values["disability_percentage"])
                if not 0 <= percentage <= 100:
                    raise ValueError("Disability percentage must be from 0 to 100.")
        except (ValueError, InvalidOperation):
            return render_template(
                profile["template"],
                message="Enter valid age, income, turnover, and disability values."
            ), 400

        education_level = values.get("education_level") or None
        social_category = values.get("category") or None
        connection = None
        cursor = None
        try:
            connection = get_connection()
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO category_profiles
                    (user_id, category_slug, age, state, district,
                     education_level, annual_income, social_category,
                     profile_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    category,
                    age,
                    values["state"],
                    values["district"],
                    education_level,
                    annual_income,
                    social_category,
                    json.dumps(values),
                )
            )
            connection.commit()
        except Exception:
            if connection is not None:
                connection.rollback()
            app.logger.exception("Failed to save %s profile", profile["role"])
            return render_template(
                profile["template"],
                message="Unable to save your profile. Please try again."
            ), 500
        finally:
            if cursor is not None:
                cursor.close()
            if connection is not None:
                connection.close()

        return redirect(url_for("category_schemes", category=category))

    return render_template(profile["template"])


@app.route("/profile/<category>/schemes")
def category_schemes(category):
    profile_roles = {
        "woman": "Woman",
        "senior-citizen": "Senior Citizen",
        "person-with-disability": "Person with Disability",
        "entrepreneur": "Entrepreneur",
        "other": "Other",
    }
    role = profile_roles.get(category)
    if role is None:
        return "Profile category not found.", 404

    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT age, state, education_level, annual_income, social_category
            FROM category_profiles
            WHERE user_id = %s AND category_slug = %s
            ORDER BY profile_id DESC
            LIMIT 1
            """,
            (user_id, category)
        )
        profile = cursor.fetchone()
        if profile is None:
            return redirect(url_for("category_profile", category=category))

        cursor.execute(
            "SELECT * FROM schemes WHERE target_role = %s",
            (role,)
        )
        schemes = cursor.fetchall()
        matched_schemes = []

        for scheme in schemes:
            eligible = True
            reasons = []

            state_reason = scheme_state_match_reason(
                scheme["state"], profile["state"]
            )
            if state_reason is None:
                eligible = False
            else:
                reasons.append(state_reason)

            if scheme["min_age"] is not None:
                if profile["age"] < scheme["min_age"]:
                    eligible = False
                else:
                    reasons.append("Your age meets the minimum requirement.")

            if scheme["max_age"] is not None:
                if profile["age"] > scheme["max_age"]:
                    eligible = False
                else:
                    reasons.append("Your age is within the required range.")

            if scheme["max_income"] is not None:
                if profile["annual_income"] > scheme["max_income"]:
                    eligible = False
                else:
                    reasons.append("Your family income is within the limit.")

            allowed_categories = scheme["category"]
            if allowed_categories and allowed_categories != "All":
                allowed_categories = [
                    item.strip().casefold()
                    for item in allowed_categories.split("/")
                ]
                if (profile["social_category"] or "").casefold() not in allowed_categories:
                    eligible = False
                else:
                    reasons.append("Your social category matches the scheme.")
            else:
                reasons.append("The scheme is open to all social categories.")

            required_education = scheme["education_level"]
            if required_education and required_education != "All":
                if required_education == "Post-Matric":
                    eligible_education = {
                        "Undergraduate", "Postgraduate", "Diploma"
                    }
                    education_matches = profile["education_level"] in eligible_education
                else:
                    education_matches = profile["education_level"] == required_education

                if not education_matches:
                    eligible = False
                else:
                    reasons.append("Your education level matches the scheme.")

            if eligible:
                scheme["status"] = "Potential Match"
                scheme["reasons"] = reasons
                matched_schemes.append(scheme)

        save_available = add_saved_scheme_status(cursor, matched_schemes, user_id)
        return render_template(
            "relevant_schemes.html",
            schemes=matched_schemes,
            scheme_save_available=save_available,
            match_note=(
                "These are potential matches based on the profile details "
                "provided. Scheme-specific conditions may not all be covered "
                "by this profile form. Confirm eligibility and application "
                "details on myScheme before applying."
            )
        )
    except Exception:
        app.logger.exception("Failed to find %s schemes", role)
        return "Unable to load relevant schemes right now.", 500
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)