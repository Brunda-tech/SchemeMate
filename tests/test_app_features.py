import os
import unittest
from unittest.mock import MagicMock, patch

from flask import render_template, session as flask_session

import app as schememate


class SavedSchemeTests(unittest.TestCase):
    def setUp(self):
        schememate.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        schememate.chat_requests_by_ip.clear()
        self.client = schememate.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 27
            session["user_name"] = "Test User"
            session["user_email"] = "test@example.test"
            session["saved_scheme_csrf_token"] = "csrf-test"

    def test_account_menu_shows_profile_and_saved_schemes(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"test@example.test", response.data)
        self.assertIn(b"Saved schemes", response.data)
        for question, _, _ in schememate.WEBSITE_FAQS:
            self.assertIn(question.encode(), response.data)

    def test_account_page_shows_profile_and_saved_count(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "name": "Test User",
                "email": "test@example.test",
                "role_name": "Student",
            }
        ]
        cursor.fetchone.return_value = {"saved_count": 1}

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.get("/account")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"test@example.test", response.data)
        self.assertIn(b"Student", response.data)
        self.assertIn(b"1 scheme saved", response.data)

    def test_account_profile_loads_when_saved_table_is_missing(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "name": "Test User",
                "email": "test@example.test",
                "role_name": "Student",
            }
        ]
        cursor.execute.side_effect = [
            None,
            schememate.MySQLDatabaseError(
                "saved_schemes table is missing",
                errno=1146,
            ),
        ]

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.get("/account")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"test@example.test", response.data)
        self.assertIn(b"Saved schemes are temporarily unavailable", response.data)

    def test_manual_website_faq_works_without_database_or_gemini(self):
        with patch.object(schememate, "get_chat_scheme_context") as get_context:
            with patch.object(schememate, "ask_gemini") as ask_gemini:
                response = self.client.post(
                    "/api/chat",
                    json={
                        "messages": [
                            {"role": "user", "content": "What is SchemeMate?"}
                        ]
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mode"], "faq")
        self.assertIn("information tool", response.json["reply"])
        get_context.assert_not_called()
        ask_gemini.assert_not_called()

    def test_every_visible_faq_prompt_has_a_manual_answer(self):
        for question, _, _ in schememate.WEBSITE_FAQS:
            with self.subTest(question=question):
                self.assertIsNotNone(schememate.find_website_faq_reply(question))

    def test_ai_failure_returns_manual_faq_prompts(self):
        with patch.object(
            schememate,
            "get_chat_scheme_context",
            return_value=([], []),
        ):
            with patch.object(
                schememate,
                "ask_gemini",
                side_effect=RuntimeError("AI unavailable"),
            ):
                response = self.client.post(
                    "/api/chat",
                    json={
                        "messages": [
                            {"role": "user", "content": "Tell me about newest schemes."}
                        ]
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mode"], "faq")
        self.assertIn("How do I save a scheme?", response.json["reply"])

    def test_saving_scheme_requires_csrf_token(self):
        with patch.object(schememate, "get_connection") as get_connection:
            response = self.client.post(
                "/scheme/42/save",
                data={"csrf_token": "invalid"},
            )

        self.assertEqual(response.status_code, 400)
        get_connection.assert_not_called()

    def test_scheme_details_offers_save_action(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.side_effect = [
            {
                "scheme_id": 42,
                "scheme_name": "Test Scheme",
                "target_role": "Student",
                "description": "A test description.",
                "category": "All",
                "education_level": "All",
                "max_income": None,
                "benefit": "A test benefit.",
                "documents": "Test documents.",
                "application_process": "Test process.",
                "official_link": "https://example.gov.in",
            },
            None,
        ]

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.get("/scheme/42")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Save this scheme", response.data)

    def test_scheme_details_still_loads_if_saved_schemes_table_is_missing(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.return_value = {
            "scheme_id": 42,
            "scheme_name": "Test Scheme",
            "target_role": "Student",
            "description": "A test description.",
            "category": "All",
            "education_level": "All",
            "max_income": None,
            "benefit": "A test benefit.",
            "documents": "Test documents.",
            "application_process": "Test process.",
            "official_link": "https://example.gov.in",
        }
        cursor.execute.side_effect = [
            None,
            schememate.MySQLDatabaseError(
                "saved_schemes table is missing",
                errno=1146,
            ),
        ]

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.get("/scheme/42?source=all")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Scheme", response.data)
        self.assertIn(b"saving is temporarily unavailable", response.data)
        self.assertIn(b'href="/schemes"', response.data)

    def test_saving_scheme_is_scoped_to_signed_in_user(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.post(
                "/scheme/42/save",
                data={"csrf_token": "csrf-test"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            cursor.execute.call_args_list[1].args[1],
            (27, 42),
        )
        connection.commit.assert_called_once()

    def test_saving_from_a_scheme_list_returns_to_that_list(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchone.return_value = (42,)

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.post(
                "/scheme/42/save",
                data={
                    "csrf_token": "csrf-test",
                    "return_to": "/jobseeker-schemes",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/jobseeker-schemes")

    def test_saved_schemes_page_uses_signed_in_user(self):
        connection = MagicMock()
        cursor = MagicMock()
        connection.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            {
                "scheme_id": 42,
                "scheme_name": "Test Scheme",
                "target_role": "Student",
                "state": "All India",
                "description": "A test description.",
                "official_link": "https://example.gov.in",
                "saved_at": "2026-11-23",
            }
        ]

        with patch.object(
            schememate,
            "get_connection",
            return_value=connection,
        ):
            response = self.client.get("/saved-schemes")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Scheme", response.data)
        self.assertEqual(cursor.execute.call_args.args[1], (27,))


class SchemeDirectoryTests(unittest.TestCase):
    def setUp(self):
        schememate.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = schememate.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = 1
            session["user_email"] = "admin@example.test"
            session["admin_csrf_token"] = "admin-csrf"

    def test_admin_added_scheme_appears_in_public_all_schemes_page(self):
        class SchemeStore:
            def __init__(self):
                self.schemes = []
                self.commits = 0
                self.public_list_query = ""

            def cursor(self, dictionary=False):
                return SchemeCursor(self)

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                pass

        class SchemeCursor:
            def __init__(self, store):
                self.store = store
                self.result = None

            def execute(self, query, params=()):
                normalized_query = " ".join(query.split())
                if "SELECT email FROM users" in normalized_query:
                    self.result = {"email": "admin@example.test"}
                elif normalized_query.startswith("INSERT INTO schemes"):
                    fields = (
                        "scheme_name", "description", "target_role", "state",
                        "min_age", "max_age", "max_income", "category",
                        "education_level", "benefit", "documents",
                        "application_process", "official_link",
                    )
                    scheme = dict(zip(fields, params))
                    scheme["scheme_id"] = 321
                    self.store.schemes.append(scheme)
                    self.result = None
                elif normalized_query.startswith("SELECT * FROM schemes"):
                    self.result = next(
                        (
                            scheme
                            for scheme in self.store.schemes
                            if scheme["scheme_id"] == params[0]
                        ),
                        None,
                    )
                elif "FROM saved_schemes" in normalized_query:
                    self.result = []
                elif "FROM schemes" in normalized_query:
                    self.store.public_list_query = normalized_query
                    self.result = list(self.store.schemes)
                else:
                    raise AssertionError("Unexpected SQL query in scheme test.")

            def fetchone(self):
                return self.result

            def fetchall(self):
                return self.result

            def close(self):
                pass

        store = SchemeStore()
        form_data = {
            "csrf_token": "admin-csrf",
            "scheme_name": "New Student Scholarship",
            "description": "A new scholarship for eligible students.",
            "target_role": "Student",
            "state": "All India",
            "min_age": "",
            "max_age": "",
            "max_income": "",
            "category": "All",
            "education_level": "All",
            "benefit": "Scholarship assistance.",
            "documents": "Check the official portal.",
            "application_process": "Apply on the official portal.",
            "official_link": "https://example.gov.in/scholarship",
        }

        with patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.test"}):
            with patch.object(schememate, "get_connection", return_value=store):
                response = self.client.post("/admin/schemes/new", data=form_data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(store.commits, 1)
                response = self.client.get("/schemes")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'aria-label="Save this scheme"', response.data)

                with self.client.session_transaction() as session:
                    session.clear()
                response = self.client.get("/schemes")
                details_response = self.client.get(
                    "/scheme/321?source=all"
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"New Student Scholarship", response.data)
        self.assertIn(b"/static/images/schemes/student.svg", response.data)
        self.assertIn(b"/scheme/321?source=all", response.data)
        self.assertIn(b"Back to Home", response.data)
        self.assertIn("FROM schemes", store.public_list_query)
        self.assertNotIn("WHERE", store.public_list_query)
        self.assertEqual(details_response.status_code, 200)
        self.assertIn(b"New Student Scholarship", details_response.data)
        self.assertIn(b"Back to All Schemes", details_response.data)

        for filename, _ in schememate.SCHEME_ILLUSTRATIONS.values():
            image_response = self.client.get(
                "/static/images/schemes/" + filename
            )
            self.assertEqual(image_response.status_code, 200)
            image_response.close()

    def test_role_results_render_save_symbol_and_structured_cards(self):
        scheme = {
            "scheme_id": 42,
            "scheme_name": "Test Scheme",
            "target_role": "Student",
            "state": "All India",
            "status": "Potential Match",
            "description": "A test description.",
            "benefit": "A test benefit.",
            "reasons": ["Your profile matches."],
            "is_saved": False,
        }

        with schememate.app.test_request_context("/jobseeker-schemes"):
            flask_session["user_id"] = 27
            flask_session["saved_scheme_csrf_token"] = "csrf-test"
            for template in ("relevant_schemes.html", "farmer_schemes.html"):
                with self.subTest(template=template):
                    for schemes in ([scheme], []):
                        html = render_template(
                            template,
                            schemes=schemes,
                            match_note=None,
                            scheme_save_available=True,
                        )

                        self.assertEqual(html.count("<main"), html.count("</main>"))
                        if schemes:
                            self.assertIn('class="scheme-card-art"', html)
                            self.assertIn('class="scheme-save-icon', html)
                            self.assertIn("Save this scheme", html)
                            self.assertEqual(
                                html.count('<article class="scheme-card">'),
                                1,
                            )


class ComplaintReportTests(unittest.TestCase):
    def setUp(self):
        schememate.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        schememate.complaint_requests_by_ip.clear()
        self.client = schememate.app.test_client()
        with self.client.session_transaction() as session:
            session["contact_csrf_token"] = "complaint-csrf"

    def complaint_data(self):
        return {
            "csrf_token": "complaint-csrf",
            "name": "Example Person",
            "email": "person@example.test",
            "address": "Bengaluru, Karnataka",
            "issue": "I encountered an issue while viewing a scheme.",
            "consent": "yes",
        }

    def test_complaint_is_emailed_to_configured_support_address(self):
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        smtp.send_message.return_value = {}
        smtp_username = "sender@example.test"
        smtp_password = "test-app-password"
        recipient = "brundagr17@gmail.com"

        with patch.dict(
            os.environ,
            {
                "SMTP_USERNAME": smtp_username,
                "SMTP_APP_PASSWORD": smtp_password,
                "COMPLAINT_RECIPIENT": recipient,
            },
        ):
            with patch.object(schememate.smtplib, "SMTP", return_value=smtp):
                response = self.client.post("/contact", data=self.complaint_data())

        self.assertEqual(response.status_code, 302)
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], recipient)
        self.assertEqual(message["Reply-To"], "person@example.test")
        self.assertIn("Bengaluru, Karnataka", message.get_content())
        self.assertIn("I encountered an issue", message.get_content())
        smtp.login.assert_called_once_with(smtp_username, smtp_password)

    def test_complaint_requires_valid_csrf_and_consent(self):
        data = self.complaint_data()
        data["csrf_token"] = "invalid"
        with patch.object(schememate.smtplib, "SMTP") as smtp:
            response = self.client.post("/contact", data=data)

        self.assertEqual(response.status_code, 400)
        smtp.assert_not_called()

        data = self.complaint_data()
        data["consent"] = ""
        response = self.client.post("/contact", data=data)
        self.assertEqual(response.status_code, 400)

    def test_complaint_reports_missing_mail_configuration(self):
        data = self.complaint_data()
        with patch.dict(
            os.environ,
            {"SMTP_USERNAME": "", "SMTP_APP_PASSWORD": ""},
        ):
            with patch.object(schememate.smtplib, "SMTP") as smtp:
                response = self.client.post("/contact", data=data)

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Open email to send your complaint", response.data)
        self.assertIn(b"mailto:brundagr17@gmail.com", response.data)
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
