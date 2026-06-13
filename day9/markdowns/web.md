Overview
FastAPI web interface for a multi-modal agent with file upload (PDF, DOCX, images, text).

Imports
fastapi, uvicorn (web server)

jinja2 (templating)

python-magic (MIME detection)

PyPDF2, python-docx (document text extraction)

Pillow (image preview)

python-dotenv (config)

API
GET / -> HTML
Returns chat interface.

GET /history -> {"history": list}
Returns conversation history with attachment metadata.

POST /send
Form data: message: str, files: List[UploadFile] (optional)
Returns {"assistant_reply": str, "history": list}

POST /reset -> {"status": "ok"}
Clears conversation history and deletes uploaded files.

GET /info -> agent metadata (ID, vision support, etc.)
Usage
python
from web import app
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8000)
Requires .env with:

text
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4