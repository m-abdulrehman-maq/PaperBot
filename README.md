# PaperBot 🎓

A WhatsApp-based university past papers assistant built for students of UET Lahore. Students can search, download, and study past papers — all through a simple WhatsApp chat interface. No app downloads. No websites. Just WhatsApp.

> Built by **Abdul** and **Tooba Sahar**

---

## The Problem

Every semester, the same cycle repeats. Juniors flood seniors' WhatsApp the night before exams:

> *"Bhai/Apa past paper bhej do please 🙏"*

Seniors are buried in their own preparation. Nobody has time. Papers don't get shared. Students panic.

PaperBot fixes this — it acts as that senior who is always available, always has the papers, and never gets busy.

---

## Features

| Feature | Description |
|---|---|
| 📄 Paper Search | Search by department, subject, year & type (Midterm / Final / Quiz) |
| 🤖 AI Solutions | Auto-generated solutions for past papers via Google Gemini |
| ❓ MCQ Generator | 10 MCQs generated on first request, cached for all future users |
| 📊 Syllabus Mapper | Most repeated topics ranked by frequency from real past paper data |
| 🎯 Smart Predictor | Predicts likely exam topics using a custom scoring algorithm — no AI calls, pure data |
| 👨‍🏫 Instructor Insights | Teaching style and difficulty analysis per instructor |
| 🔖 Bookmarks | Save papers for quick access later |
| 🎫 Support Tickets | Users can submit issues directly through WhatsApp |
| 🛠️ Admin Panel | Full web dashboard for paper management, AI content, analytics, and settings |

---

## Architecture

```
WhatsApp User
      ↓
WhatsApp Cloud API
      ↓
DigitalOcean Functions (Webhook — __main__.py)
      ↓
Turso Database (LibSQL over HTTP)
      ↓
DigitalOcean App Platform (Flask Admin Panel + Background Worker)
      ↓
Google Gemini AI ← for solutions, MCQs, instructor insights
Supabase Storage ← for PDF files
```

| Component | Platform | Location |
|---|---|---|
| WhatsApp Bot (webhook) | DigitalOcean Functions | `packages/default/PaperBot/__main__.py` |
| Admin Panel + Worker | DigitalOcean App Platform | `webapp/` |
| Database | Turso (LibSQL, HTTP API) | `db/schema.sql` |
| PDF Storage | Supabase Storage (S3-compatible) | — |
| AI | Google Gemini (REST) | `webapp/ai.py` |

The database is accessed entirely over Turso's HTTP API using only the Python standard library — **no database driver needed**. The DigitalOcean Function has zero third-party dependencies.

---

## Smart Predictor Algorithm

The Paper Predictor uses **zero AI calls**. Instead it uses a custom scoring algorithm based on real past paper data:

```python
score = (frequency × 10) + (years_gap × 8) + (year_spread × 5)
```

- **Frequency** — how many times a topic appeared across all papers
- **Years gap** — how many years since the topic last appeared (overdue = higher chance)
- **Year spread** — how many different years the topic appeared in (consistency)

Topics are then ranked into High / Medium / Low chance categories — giving students data-driven predictions instantly.

---

## Tech Stack

- **Python & Flask** — bot logic and admin panel
- **WhatsApp Cloud API** — bot interface
- **Google Gemini AI** — solution and MCQ generation
- **Turso (LibSQL)** — database over HTTP API
- **Supabase Storage** — PDF file storage
- **DigitalOcean Functions** — serverless webhook
- **DigitalOcean App Platform** — admin panel and background worker hosting
- **cPanel** — admin panel alternate hosting

---

## Project Structure

```
paperbot/
├── packages/
│   └── default/
│       └── PaperBot/
│           └── __main__.py      # WhatsApp bot — webhook handler
├── webapp/
│   ├── app.py                   # Flask admin panel
│   ├── worker.py                # Background job processor
│   ├── ai.py                    # Gemini AI calls
│   ├── db.py                    # Turso HTTP API layer
│   ├── config.py                # Environment config
│   ├── storage.py               # Supabase PDF storage
│   ├── templates/               # Admin panel HTML templates
│   └── requirements.txt
├── db/
│   └── schema.sql               # Database schema
├── app.yaml                     # DigitalOcean App Platform spec
├── project.yml                  # DigitalOcean Functions spec
└── .env.example                 # Environment variables template
```

---

## Setup & Deployment

### 1. Clone the repo

```bash
git clone https://github.com/your-username/paperbot.git
cd paperbot
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in all values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `WHATSAPP_TOKEN` | Meta WhatsApp Cloud API token |
| `PHONE_NUMBER_ID` | WhatsApp Business phone number ID |
| `VERIFY_TOKEN` | Webhook verify token |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | Gemini model name (recommended: `gemini-2.0-flash`) |
| `TURSO_DATABASE_URL` | Turso database URL |
| `TURSO_AUTH_TOKEN` | Turso auth token |
| `SECRET_KEY` | Flask secret key (long random string) |
| `ADMIN_USERNAME` | Admin panel username |
| `ADMIN_PASSWORD` | Admin panel password |
| `SPACES_KEY` | Supabase storage access key |
| `SPACES_SECRET` | Supabase storage secret |
| `SPACES_ENDPOINT` | Supabase storage endpoint |
| `SPACES_BUCKET` | Storage bucket name |
| `WORKER_ENABLED` | Set `true` on App Platform, `false` on cPanel |

### 3. Database (Turso)

```bash
turso db create paperbot
turso db show paperbot           # copy URL → TURSO_DATABASE_URL
turso db tokens create paperbot  # copy token → TURSO_AUTH_TOKEN
python init_db.py                # apply schema
```

### 4. Deploy Admin Panel (DigitalOcean App Platform)

```bash
doctl apps create --spec app.yaml
```

First admin user is created automatically from `ADMIN_USERNAME` and `ADMIN_PASSWORD` on first boot.

### 5. Deploy WhatsApp Bot (DigitalOcean Functions)

```bash
doctl serverless deploy .
```

Point your Meta webhook to the function URL and use `VERIFY_TOKEN` to verify.

### 6. Local Development (Admin Panel only)

```bash
cd webapp
pip install -r requirements.txt
export $(grep -v '^#' ../.env | xargs)
python app.py
# Admin panel at http://localhost:8080
```

---

## How It Works

```
User sends "Hi" on WhatsApp
        ↓
Bot replies with welcome message
        ↓
User types "menu"
        ↓
Bot shows: Search Papers / Bookmarks / Syllabus Mapper / Instructor Insights / Paper Predictor / Help
        ↓
User selects Search → picks Department → Subject → Year → Type
        ↓
Bot sends matching past papers as PDF links
        ↓
User can request Solution / MCQs for any paper
        ↓
Worker checks DB cache → if not found → calls Gemini → stores → sends to user
        ↓
Next user requesting same paper gets instant response from cache
```

---

## Admin Panel

Accessible at your deployed webapp URL. Features include:

- **Dashboard** — active users, papers, jobs overview
- **Users** — all WhatsApp users and their activity
- **Papers** — upload, manage, and organize past papers
- **Content** — manage departments, subjects, and instructors
- **AI** — view generated solutions/MCQs, regenerate or upload manually
- **Support** — view and resolve user support tickets
- **Settings** — daily AI limit, bot messages, maintenance mode

---

## Security

- `.env` is git-ignored — never commit real tokens
- Admin panel is password protected — use a strong `ADMIN_PASSWORD` and a long random `SECRET_KEY`
- WhatsApp webhook is verified using `VERIFY_TOKEN` on every request

---

## Roadmap

- [x] Paper search by department, subject, year, type
- [x] AI solutions and MCQs with DB caching
- [x] Syllabus Mapper
- [x] Smart Paper Predictor (no AI)
- [x] Instructor Insights
- [x] Support ticket system
- [x] Admin panel
- [ ] Expand to more departments at UET Lahore (target: 100+ users)
- [ ] Quiz paper type with dedicated flow
- [ ] Usage analytics dashboard

---

## Contributors

| Name | Role |
|---|---|
| Abdul | Lead Developer |
| Tooba Sahar | Co-Developer |

---

## License

This project is for educational purposes. All rights reserved.

---

> Currently live for the **Computer Engineering department of UET Lahore**
> 💬 Try it: 03704989753
