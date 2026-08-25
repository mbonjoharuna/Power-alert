# Douala Power Alert

**Une carte participative des coupures d'électricité avec estimations de rétablissement, aidant les habitants à s'organiser face au délestage.**

A simple web application for a school coding challenge. Residents of Douala can report electricity outages, see neighborhood status, confirm if power is still off, and check estimated restoration times.

---

## 1. Project objective

Help residents of Douala know whether an electricity outage affects only their home or an entire neighborhood, and organize themselves during load-shedding (délestage).

## 2. Problem being solved

- People do not know if an outage is local or widespread.
- No shared, real-time view of reported outages by neighborhood.
- No simple way to share estimated restoration times (community estimates, not official).

## 3. Solution

A lightweight web platform where:

- Residents **register**, **login**, and **report** outages.
- The community can **see** reports, **confirm** “still OFF” or “RESTORED”.
- Admins **approve / reject / mark restored** and set **estimated restoration** times.
- A **simple map** shows outage locations in Douala.
- A **simple AI assistant** answers questions using data from the database.

## 4. Features

### Users

- Register (full name, email, phone, password, neighborhood)
- Login / logout (Flask sessions)
- Dashboard (active outages, my reports, verified, restored)
- Report an outage (neighborhood, location, description, start time)
- View outage list with search (neighborhood, location, status)
- View outage details
- Confirm: “Electricity is still OFF” or “Electricity is RESTORED” (once per outage)
- My reports
- AI assistant

### Admins

- Admin login
- Dashboard: total users, reports, pending, verified, restored
- Approve, Reject, Mark Restored, Update Estimate, Delete

### Map

- Simple Leaflet map centered on Douala
- Markers colored by status (red = OFF/verified, yellow = pending, green = restored)

### AI

- Rule-based answers from MySQL data (works without an API key)
- Optional external API if `AI_API_KEY` is set in `.env`
- Never invents restoration times

## 5. Technologies

| Layer        | Technology              |
|-------------|--------------------------|
| Backend     | Python, Flask            |
| Database    | MySQL                    |
| Frontend    | HTML5, CSS3, JavaScript  |
| Map         | Leaflet (CDN)            |
| Security    | Werkzeug password hashing, Flask sessions, parameterized SQL |

**Not used:** React, Vue, Angular, Node.js, PHP, MongoDB, Django.

## 6. Database tables

Exactly **4 tables**:

### users

| Column         | Type         | Notes                    |
|----------------|--------------|--------------------------|
| id             | INT PK       | Auto-increment           |
| full_name      | VARCHAR(150) | Required                 |
| email          | VARCHAR(150) | UNIQUE                   |
| phone          | VARCHAR(20)  | UNIQUE                   |
| password_hash  | VARCHAR(255) | Hashed (never plain text)|
| neighborhood   | VARCHAR(100) | Required                 |
| created_at     | TIMESTAMP    | Default now              |

### admins

| Column         | Type         | Notes          |
|----------------|--------------|----------------|
| id             | INT PK       | Auto-increment |
| username       | VARCHAR(100) | UNIQUE         |
| password_hash  | VARCHAR(255) | Hashed         |
| created_at     | TIMESTAMP    | Default now    |

### outages

| Column            | Type     | Notes                                      |
|-------------------|----------|--------------------------------------------|
| id                | INT PK   | Auto-increment                             |
| user_id           | INT FK   | → users(id)                                |
| neighborhood      | VARCHAR  | e.g. Bonamoussadi                          |
| location          | VARCHAR  | Landmark                                   |
| description       | TEXT     | Optional                                   |
| start_time        | DATETIME | When power went off                        |
| estimated_restore | DATETIME | NULL until admin sets it                   |
| status            | ENUM     | PENDING, VERIFIED, RESTORED, REJECTED      |
| created_at        | TIMESTAMP|                                            |
| updated_at        | TIMESTAMP| Auto-updated                               |

### confirmations

| Column       | Type     | Notes                              |
|--------------|----------|------------------------------------|
| id           | INT PK   | Auto-increment                     |
| outage_id    | INT FK   | → outages(id)                      |
| user_id      | INT FK   | → users(id)                        |
| confirmation | ENUM     | STILL_OFF or RESTORED              |
| created_at   | TIMESTAMP|                                    |

**Unique constraint:** one confirmation per (outage_id, user_id).

## 7. Flask routes

| Route                         | Method   | Description                |
|-------------------------------|----------|----------------------------|
| `/`                           | GET      | Home + map                 |
| `/register`                   | GET/POST | User registration          |
| `/login`                      | GET/POST | User login                 |
| `/logout`                     | GET      | Logout                     |
| `/dashboard`                  | GET      | User dashboard             |
| `/report`                     | GET/POST | Report an outage           |
| `/outages`                    | GET      | List + search outages      |
| `/outage/<id>`                | GET      | Outage details             |
| `/outage/<id>/confirm`        | POST     | Confirm still OFF / restored |
| `/my-reports`                 | GET      | Current user’s reports     |
| `/ai`                         | GET/POST | AI assistant               |
| `/admin/login`                | GET/POST | Admin login                |
| `/admin/logout`               | GET      | Admin logout               |
| `/admin/dashboard`            | GET      | Admin dashboard            |
| `/admin/approve/<id>`         | POST     | Approve (VERIFIED)         |
| `/admin/reject/<id>`          | POST     | Reject                     |
| `/admin/restore/<id>`         | POST     | Mark RESTORED              |
| `/admin/update/<id>`          | POST     | Update estimated restore   |
| `/admin/delete/<id>`          | POST     | Delete report              |
| `/api/outages/map`            | GET      | JSON markers for the map   |

## 8. AI integration

- File: `services/ai_service.py`
- API key stored only in `.env` (never hard-coded)
- Flow:

```
USER → AI QUESTION → FLASK → GET RELEVANT OUTAGE DATA FROM MYSQL
     → AI API (or rule-based) → FLASK → AI RESPONSE → USER
```

- If no verified estimate exists, the system answers:  
  **“No verified restoration estimate is currently available.”**

## 9. Map

- Leaflet via CDN (lightweight)
- Approximate coordinates for Douala neighborhoods (Bonamoussadi, Deido, Akwa, etc.)
- Markers loaded from `/api/outages/map`
- No complex GIS

## 10. Security

- Passwords hashed with Werkzeug (`generate_password_hash` / `check_password_hash`)
- Flask sessions for user and admin authentication
- Parameterized SQL (no string concatenation of user input)
- Server-side and client-side form validation
- Admin routes protected by `@admin_required`
- API keys only in `.env`

## 11. Installation

### Prerequisites

- Python 3.8+
- MySQL (or XAMPP / WAMP / MariaDB)
- pip

### Steps

```bash
# 1. Go to the project folder
cd douala_power_alert

# 2. Create a virtual environment (recommended)
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env   # Windows
# or: cp .env.example .env

# Edit .env with your MySQL password and (optional) AI key
```

## 12. XAMPP / MySQL setup

1. Start **Apache** and **MySQL** in XAMPP.
2. Open phpMyAdmin: `http://localhost/phpmyadmin`
3. Go to **SQL** tab and paste the contents of `database.sql`, then click **Go**.
4. Or from the command line:

```bash
mysql -u root -p < database.sql
```

This creates the database `douala_power_alert` and the 4 tables.

**Default admin (created/updated when the app starts):**

- Username: `admin`
- Password: `admin123`

## 13. .env configuration

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=douala_power_alert

SECRET_KEY=any-random-string-for-sessions

# Optional – leave empty to use built-in rule-based answers
AI_API_KEY=
AI_API_URL=https://api.openai.com/v1/chat/completions
AI_MODEL=gpt-3.5-turbo
```

## 14. How to run the application

```bash
python app.py
```

Then open: **http://127.0.0.1:5000**

---

## Application data flow

```
USER
 ↓
HTML FORM
 ↓
JAVASCRIPT VALIDATION
 ↓
FLASK (route + validation)
 ↓
MYSQL (parameterized queries)
 ↓
FLASK
 ↓
JINJA TEMPLATE (render_template)
 ↓
HTML
 ↓
USER
```

**AI flow:**

```
USER
 ↓
AI QUESTION
 ↓
FLASK
 ↓
GET RELEVANT OUTAGE DATA FROM MYSQL
 ↓
AI API (or rule-based)
 ↓
FLASK
 ↓
AI RESPONSE
 ↓
USER
```

---

## Team of 5 — responsibilities

| Member | Responsibility                          |
|--------|-----------------------------------------|
| 1      | Flask backend (`app.py`, routes)        |
| 2      | MySQL database (`database.sql`, queries)|
| 3      | HTML / CSS (templates, `style.css`)     |
| 4      | JavaScript + map (`script.js`, Leaflet) |
| 5      | AI service + testing (`ai_service.py`)  |

Every member should understand the basic flow above.

---

## Concepts explained simply (for beginners)

| Concept | Simple meaning |
|--------|----------------|
| **Flask** | A small Python web framework. You write routes; Flask answers HTTP requests. |
| **GET** | Request used to **read** a page (e.g. open `/outages`). |
| **POST** | Request used to **send** data (e.g. submit a form). |
| **request** | Flask object that holds form data, query parameters, etc. |
| **render_template()** | Loads an HTML file (Jinja template) and fills it with data. |
| **redirect()** | Sends the user to another URL after an action. |
| **url_for()** | Builds a URL from a route function name (safer than hard-coding). |
| **sessions** | Server-side storage so the app “remembers” who is logged in. |
| **CRUD** | Create, Read, Update, Delete — the four basic database operations. |
| **Primary key** | Unique ID of a row (e.g. `users.id`). |
| **Foreign key** | Column that points to a primary key in another table (e.g. `outages.user_id`). |
| **SQL JOIN** | Combine rows from two tables (e.g. outages + users to show the reporter’s name). |
| **Password hashing** | Store a one-way fingerprint of the password, not the password itself. |
| **API** | A way for programs to talk (e.g. our `/api/outages/map` returns JSON for the map). |
| **JSON** | Text format for structured data (`{"status": "VERIFIED"}`). |
| **AI integration** | We send a question + outage context to a model (or rules) and show the answer. |

---

## Project structure

```
douala_power_alert/
├── app.py
├── database.sql
├── requirements.txt
├── .env.example
├── README.md
├── services/
│   ├── __init__.py
│   └── ai_service.py
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── register.html
│   ├── login.html
│   ├── dashboard.html
│   ├── report.html
│   ├── outages.html
│   ├── outage_details.html
│   ├── my_reports.html
│   ├── ai.html
│   └── admin/
│       ├── admin_login.html
│       └── admin_dashboard.html
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── script.js
```

---

## Status values

| Status    | Meaning                                      |
|-----------|----------------------------------------------|
| PENDING   | Waiting for admin verification               |
| VERIFIED  | Outage confirmed                             |
| RESTORED  | Electricity has returned                     |
| REJECTED  | Invalid or duplicate report                  |

---

## License / note

School coding challenge project. Keep it simple, professional, and easy to explain.  
Estimated restoration times are **community estimates, not official guarantees**.
