LLM Agent Chat with File Support
FastAPI backend with multimodal (text + file attachments) chat agent.

Imports
fastapi, uvicorn, python-multipart, aiofiles, PIL (Pillow), pypdf, python-docx, httpx

API
Function	Signature	Description
GET /history	() -> dict	Returns {"history": list[Message]}
GET /info	() -> dict	Returns {"agent_id": str, "supports_vision": bool}
POST /send	(message: str = Form(""), files: list[UploadFile] = File([])) -> dict	Accepts text+files, returns {"history": list[Message]}
POST /reset	() -> dict	Clears conversation history
Usage
python
import httpx

# Send text + image
files = {"files": ("photo.jpg", open("cat.jpg", "rb"), "image/jpeg")}
resp = httpx.post("http://localhost:8000/send", data={"message": "What's this?"}, files=files)
print(resp.json()["history"][-1]["content"])
Notes
Supports: images (auto-resized to 768px max), PDF (extracts first 5 pages), DOCX (extracts text), TXT, MD, PY

Images: vision model required; otherwise sends [Image attached: filename] placeholder

File size limit: 10MB per file (enforced client-side)

In-memory session; reset clears all messages

Typing indicator + file preview in HTML frontend