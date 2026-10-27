# AI Study Assistant with RAG and Agentic AI

An AI-powered academic study assistant that helps students explore study materials and get context-aware answers using Retrieval-Augmented Generation (RAG) and Large Language Models (LLMs).

## Features

- Ask questions about academic study materials.
- Retrieve relevant context to generate answers.
- Use an AI agent to support research-related queries.
- Interact through a web-based user interface.

*Note: Include only the features that are implemented and working in your project.*

## Tech Stack

- **Frontend:** React.js, Vite
- **Backend:** Python, Django REST Framework
- **AI:** Large Language Models (LLMs), Retrieval-Augmented Generation (RAG)
- **Vector Database:** ChromaDB, if configured in the project

## Project Structure

```text
study-assistant/
├── backend/
│   ├── api/
│   │   ├── agent.py
│   │   ├── agent_views.py
│   │   ├── llm.py
│   │   ├── rag.py
│   │   └── views.py
│   ├── config/
│   ├── manage.py
│   └── requirements.txt
└── frontend/
    ├── src/
    ├── package.json
    └── vite.config.js
```

## Getting Started

### Prerequisites

- Python
- Node.js and npm
- Git

### 1. Clone the repository

```bash
git clone https://github.com/Anagha707/study-assistant.git
cd study-assistant
```

### 2. Set up the backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run database migrations and start the server:

```bash
python manage.py migrate
python manage.py runserver
```

### 3. Set up the frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL displayed in the terminal.

## Environment Variables

Configure the required API keys and other settings in a local `.env` file, according to your backend configuration. Never commit API keys, passwords, or other secrets to GitHub.

## Future Improvements

- Improve research-focused retrieval.
- Add source references for generated answers.
- Expand academic document analysis capabilities.

## Author

**Anagha S Anil**

GitHub: [Anagha707](https://github.com/Anagha707)
