# SchemeMate chatbot setup

The chatbot works in database-suggestion mode without an AI key. To enable
Gemini-generated replies:

1. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Open the `.env` file in the project root and replace
   `put_your_gemini_api_key_here` with your key.
3. Optionally change `GEMINI_MODEL` in `.env`. The default is
   `gemini-3.8-flash`.
4. Restart Flask so it loads the updated settings.

The project loads `.env` when Flask starts, and Git ignores that file. Never put
the API key in `app.py`, templates, JavaScript, or a committed file.
SchemeMate sends chat messages and a short list of matching scheme records to
Gemini to generate a reply. SchemeMate does not save chatbot conversations;
avoid entering sensitive personal information. Replies are informational only,
and eligibility must be confirmed on each linked official scheme source.
The chatbot also includes eight built-in SchemeMate FAQ prompts. These work
without Gemini or the scheme database; if an AI request fails, the chatbot
offers the FAQ prompts as an offline fallback.

## Complaint email setup

The Contact page sends complaint reports to `brundagr17@gmail.com`. Configure
the sending Gmail account in the project-root `.env` using
`SMTP_USERNAME` and `SMTP_APP_PASSWORD`. Use a Google App Password (with
two-step verification enabled), not the account's normal password. The
`COMPLAINT_RECIPIENT` setting is optional and defaults to the address above.
Never commit or share the app password. Reports are emailed and are not stored
in the SchemeMate database. If SMTP is unavailable, the contact page offers a
pre-filled email link; the visitor must send that email themselves.

## Admin scheme management

The admin area lets the configured administrator add, edit, and delete schemes.
To enable it:

1. Register or log in with the account you want to use as administrator.
2. Set `ADMIN_EMAILS` in the project-root `.env` to the login emails that should
   have admin access, separated by commas. For example:
   `ADMIN_EMAILS=you@example.com,teammate@example.com`.
   Each person must have their own SchemeMate account. The older `ADMIN_EMAIL`
   setting is also supported for a single address.
3. Keep the generated `FLASK_SECRET_KEY` in `.env` private; it protects login
   sessions. If it is unset, Flask uses a temporary key and sessions expire
   when the server restarts.
4. Restart Flask, sign in with that account, and open `/admin/schemes`.

The admin check uses the account email stored in the database, and admin
modification forms require a session CSRF token. Keep `.env` out of source
control. Added and updated schemes are available in the public `/schemes`
directory across all target roles; personalized match pages remain role-specific.

## Account and saved schemes

The account menu is shown to signed-in users and links to their profile and
saved schemes. Saving is available from a scheme's detail page. Ensure the
`saved_schemes` table is created by running `database/schememate.sql` against
the configured `schememate` database after its core `users` and `schemes`
tables exist.
