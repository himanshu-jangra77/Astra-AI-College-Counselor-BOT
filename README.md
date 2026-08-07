# CollegeBot — AI Admission Counselor

A simplified AI-powered college admissions chatbot for India, powered by **OpenRouter** LLMs.

## Project Structure

```
NEW_COLLEGE_Bot/
├── app.py              # FastAPI backend + OpenRouter integration
├── College_data.csv    # Dataset: 6,700+ Indian colleges
├── colleges.db         # Auto-generated SQLite database
├── requirements.txt    # Python dependencies
├── .env                # API keys and configuration (edit this!)
└── static/
    └── index.html      # Frontend chat UI
```

## Quick Start

### 1. Configure your environment variables

Copy the example environment file and add your OpenRouter API key:
```bash
cp .env.example .env
```
Edit `.env` and set:
```env
OPENROUTER_API_KEY=your_actual_key_here
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct
```
Get your key from: https://openrouter.ai/keys

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the server

```bash
python app.py
```

Visit **http://localhost:8000** in your browser.

## API Endpoints

| Method | Endpoint       | Description                    |
|--------|----------------|--------------------------------|
| GET    | `/`            | Chat UI (served from static/)  |
| GET    | `/api/health`  | Health check + config status   |
| POST   | `/api/chat`    | Send a message to the bot      |
| POST   | `/api/reset`   | Clear conversation history     |
| GET    | `/api/colleges`| Direct database search/filter  |

### Query Parameters for `/api/colleges`
- `state` — filter by state (e.g. `Tamil nadu`)
- `stream` — filter by stream (e.g. `Engineering`)
- `max_fee` — max UG annual fee in rupees
- `q` — search by college name
- `limit` — max results (1-100, default 20)

## Supported OpenRouter Models

- `meta-llama/llama-3.3-70b-instruct` (default, free)
- `deepseek/deepseek-chat`
- `anthropic/claude-3.5-sonnet`
- `google/gemini-2.0-flash-001`
- `openai/gpt-4o-mini`

## Notes

- No Docker required — runs directly with Python
- No Ollama required — uses OpenRouter cloud API
- Database is auto-created from `College_data.csv` on first run
- Conversation history is kept in-memory (resets on server restart)
