SchemeMate 🎓
Discover government schemes that may match your profile.

SchemeMate is a web application designed to make government welfare and support schemes easier to discover. Users can create an account, choose a profile category, provide relevant eligibility details, explore potentially matching schemes, save schemes for later, and ask questions through an integrated chatbot.
Important: SchemeMate is an independent information tool, not a government agency. Scheme matches are suggestions only. Always verify eligibility, benefits, deadlines, documents, and application instructions on the linked official government source.

✨ Features
- User registration and login – Create an account and sign in securely using password hashing.
- Profile-based scheme discovery – Choose a profile such as Student, Farmer, Job Seeker, Entrepreneur, Woman, Senior Citizen, Person with Disability, or Other.
- Eligibility-oriented matching – Compare profile details with available scheme records using criteria such as role, state, age, income, category, and education level.
- Scheme information – View descriptions, benefits, documents, application process, and official links where available.
- Saved schemes – Save relevant schemes to a personal list and remove them later.
- AI-assisted chatbot – Ask questions about schemes. When configured, Google Gemini generates responses grounded in matching SchemeMate records.
- Fallback chatbot – Built-in FAQs and database-based suggestions remain available when Gemini is not configured.
- Admin scheme management – Authorized administrators can add and edit scheme records.
- Contact/complaint email – The contact form can send reports by email when SMTP is configured.
🧰 Tech Stack
Layer	Technology
Backend	Python, Flask
Database	MySQL
Database connectivity	mysql-connector-python
Frontend	HTML, CSS, JavaScript, Jinja templates
Authentication	Werkzeug password hashing
Environment configuration	python-dotenv
AI chatbot (optional)	Google Gemini API
Email (optional)	SMTP


📁 Project Structure
SchemeMate/
├── app.py                  # Flask application, routes, matching and chatbot logic
├── database.py             # MySQL connection helper
├── requirements.txt        # Python dependencies (populate before installation)
├── .env                    # Local secrets and configuration (do not commit)
├── .gitignore
├── CHATBOT_SETUP.md        # Gemini chatbot and email configuration notes
├── TEAMMATE_PROGRESS.md    # Project progress notes
├── database/               # Database-related files
├── static/                 # CSS, JavaScript, images and other static assets
├── templates/              # Jinja HTML templates
├── tests/                  # Automated tests
└── .vscode/                # Editor configuration
⚙️ Getting Started
1. Clone the repository
git clone https://github.com/Brunda-tech/SchemeMate.git
cd SchemeMate
2. Create and activate a virtual environment
Windows PowerShell
py -m venv venv
.\venv\Scripts\Activate.ps1
macOS / Linux
python3 -m venv venv
source venv/bin/activate
3. Install dependencies
The repository currently contains an empty requirements.txt. Install the packages used by the application:
pip install Flask mysql-connector-python python-dotenv
If additional imports are added later, install those packages and update requirements.txt. You can generate a dependency snapshot with:
pip freeze > requirements.txt
4. Configure MySQL
1. Install and start MySQL Server.
2. Create a database named schememate.
3. Import or run the SQL schema/data scripts provided in the database/ folder, if present.
4. Configure the database connection in database.py.
Security recommendation: Do not keep database credentials directly in source code. Read the host, username, password, and database name from environment variables instead. Use a dedicated database user with only the permissions the application needs.

Example .env configuration:
FLASK_SECRET_KEY=replace_with_a_long_random_secret
DB_HOST=localhost
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_NAME=schememate

# Optional Gemini chatbot
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash

# Optional contact/complaint email
SMTP_USERNAME=
SMTP_APP_PASSWORD=
COMPLAINT_RECIPIENT=
Update database.py to read the DB_* variables before using this example configuration. Never commit .env or share API keys, database passwords, Flask secrets, or email app passwords.
5. Run the application
python app.py
Open the local address printed by Flask in your browser (commonly http://127.0.0.1:5000/).
🤖 Gemini Chatbot Setup (Optional)
The chatbot can work without a Gemini API key by using built-in FAQ responses and database-based scheme suggestions.

To enable Gemini-generated answers:
1. Create an API key through Google AI Studio.
2. Add the key to the local .env file as GEMINI_API_KEY.
3. Optionally set GEMINI_MODEL to a model available to your API key.
4. Restart the Flask application.
The chatbot is designed to use matching SchemeMate scheme records as context and should not be treated as an official eligibility decision. Avoid entering Aadhaar numbers, passwords, bank details, or other sensitive personal information. Refer to CHATBOT_SETUP.md for the project's additional chatbot notes.
✉️ Email Configuration (Optional)
The contact/complaint email feature requires SMTP settings in .env. For Gmail, use an App Password with two-step verification enabled rather than your normal account password. Keep these credentials private. Reports sent by email should not be assumed to be stored in the application database.
🔐 Security and Privacy
- Keep .env out of version control.
- Use a strong, persistent FLASK_SECRET_KEY in deployed environments.
- Store database credentials in environment variables, not in Python source files.
- Use a least-privilege MySQL account instead of a database administrator account.
- Keep dependencies updated and review authentication, authorization, CSRF, rate-limiting, and input-validation behavior before production deployment.
- Do not enter sensitive identity, banking, or authentication information into the chatbot.
- Confirm all scheme details through official government sources.
🧪 Tests
A tests/ directory is included in the repository. Run the available tests with:
python -m pytest
If pytest is not installed:
pip install pytest
🗺️ Future Improvements
- Maintain a verified, regularly updated scheme catalogue with official source references.
- Add clearer eligibility explanations showing which profile criteria matched.
- Add automated tests for authentication, scheme matching, saved schemes, admin access, and chatbot fallback behavior.
- Improve deployment configuration, database migrations, logging, and monitoring.
- Add accessibility and multilingual improvements for a wider range of users.
⚠️ Disclaimer
SchemeMate helps users discover and understand potentially relevant government schemes. It does not guarantee eligibility, provide legal advice, submit applications on behalf of users, or represent any government department. Scheme information can change; users must verify the latest details with the official department or portal.
👩‍💻 Author
Developed by Brunda-tech.
If you find the project useful, consider starring the repository!
