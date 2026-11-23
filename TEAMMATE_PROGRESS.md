# SchemeMate — Progress Update

**Updated:** 29 October 2026

## Project

SchemeMate is a Flask web app intended to help people discover government schemes based on their profile. The current UI includes student, farmer, and job-seeker profile pages.

## Implemented

- Home, About, Contact, registration, login, and role-selection pages.
- Password hashing and MySQL-backed account registration/login logic.
- Student and farmer profile forms that save submitted data to MySQL.
- Student and farmer scheme-list pages with eligibility checks and scheme detail pages.
- A job-seeker profile form and a POST handler that saves submissions to the `jobseeker_profiles` table.
- Job-seeker profiles are stored per user and redirected to matching schemes. Matching checks role, age, state, and qualification.
- Woman, senior-citizen, disability-support, entrepreneur, and general profile forms. Their submissions are stored in `category_profiles` and matched against schemes using role, age, state, income, category, and education requirements.

## Current status and remaining work

- **Student/farmer flows:** Routes and database operations are implemented, but they require a configured MySQL database with the expected tables and scheme data.
- **Job-seeker flow:** Profile submissions are saved, but job-seeker scheme matching is not implemented. The profile is not connected to the role-selection flow.
- **Additional category profiles:** The `category_profiles` table and starter scheme records have been added to the configured MySQL database. The SQL file includes the profile table, job-seeker user-link migration, and idempotent starter scheme records for a fresh/existing project database. Scheme results are potential matches; users must verify scheme-specific eligibility on myScheme.
- **Database setup:** `requirements.txt` is empty and the SQL file includes only incremental setup for profile features and their starter schemes, not the full project schema.
- **Job-seeker styling:** Its template references `static/style.css`, while the stylesheet in this project is at `static/css/style.css`.
- **Configuration before sharing/deployment:** Set database credentials for each developer's local MySQL instance, and replace the hardcoded Flask session key with a private environment-based value.

## Suggested next steps

1. Add and verify a MySQL schema and sample scheme data for the tables used by the app (`users`, `roles`, `user_roles`, `student_profiles`, `farmer_profiles`, and `schemes`).
2. Add Flask and MySQL connector dependencies to `requirements.txt`.
3. Finish the job-seeker flow: connect role selection, save profiles, and implement scheme matching.
4. Fix the job-seeker stylesheet path and move local secrets out of source code.
5. Test registration, login, profile submission, and scheme results against a clean database.

## Run locally

Prerequisites: Python 3 and a local MySQL server. The app expects a MySQL database named `schememate`; the schema is not currently included.

From the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install Flask mysql-connector-python
python app.py
```

Open `http://127.0.0.1:5000/` in a browser. The home page can be tried once the Python packages are installed. Registration, login, and profile flows also require the MySQL database, tables, and connection settings to be configured first.

## Handoff note

This update describes the current code snapshot; the main blocker to a complete end-to-end demo is the missing database schema and seed data.
