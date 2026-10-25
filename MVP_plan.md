Here is a comprehensive MVP project plan for building your Indian-context AI conflict mediator. This plan uses **Next.js** for a responsive, mobile-first frontend, **FastAPI** for a high-performance Python backend, and the official **Google GenAI SDK** to connect with the Gemini API.

## 1. MVP Scope & Core Features

**Goal:** Prove the concept of a culturally-aware "Shuttle Diplomacy" mediator that handles Indian personal/family disputes safely and anonymously.

* **Secure Session Creation:** User A creates a "Dispute Room" and shares a secure link via WhatsApp to User B.
* **Private Intake (Venting Phase):** Separate chat interfaces where each user explains the conflict in Hinglish/English.
* **AI Translation & Summary:** The backend processes the intake, translating cultural friction and emotional accusations into Non-Violent Communication (NVC) needs.
* **Joint Resolution View:** A shared dashboard where the AI presents the neutralized perspectives and suggests 2-3 culturally appropriate compromises.

---

## 2. Architecture & Data Flow

* **Frontend (Next.js - App Router):** Handles the UI, state management, and routing. Uses React Server Components for fast loading and secure data fetching.
* **Backend (FastAPI):** Serves as the orchestration layer. It receives chat messages, manages session states, and communicates securely with the Gemini API.
* **Database (PostgreSQL / Supabase):** Stores active sessions, anonymized chat logs, and relationship context.
* **LLM (Gemini API):** Processes natural language, understands Hinglish, and applies the mediation prompt.

---

## 3. Technology Stack Breakdown

| Component | Technology | Rationale |
| --- | --- | --- |
| **Frontend** | Next.js (React), Tailwind CSS | Fast rendering, easy mobile-responsive design, and clean file-based routing. |
| **Backend** | FastAPI (Python) | High concurrency (ASGI), built-in Pydantic data validation, and native async support for AI API calls. |
| **Database** | Supabase (PostgreSQL) | Quick setup, built-in row-level security (crucial for keeping User A and User B's chats isolated). |
| **AI/LLM** | Gemini API (via `google-genai` SDK) | Exceptional multilingual support (Hinglish/Indian languages) and fast inference. |

---

## 4. MVP Execution Plan (4-Week Timeline)

### Week 1: Setup & Backend Foundation

* **Project Initialization:** Set up the Next.js frontend repository and the FastAPI backend repository.
* **Database Schema Design:**
* `Sessions` table: `session_id`, `status` (intake, joint_review, resolved), `created_at`.
* `Messages` table: `message_id`, `session_id`, `user_role` (user_a, user_b, ai), `content`, `is_private`.


* **FastAPI Setup:** Define core endpoints (Create Session, Send Message, Get Session Status).
* **Gemini Integration:** Initialize the `google-genai` client in FastAPI and set up the system instruction.

### Week 2: AI Prompt Engineering & Logic

* **Prompt Design:** Craft the system prompt to enforce Indian cultural awareness, neutrality, and Hinglish understanding.
* **Intake Logic:** Build the API logic to handle the "Shuttle Diplomacy" phase. The backend must ingest messages from User A and B separately without cross-contamination.
* **Summary Engine:** Create the function that triggers Gemini to synthesize both private chats into a unified, neutral summary once both parties click "Ready for Joint Session."

### Week 3: Frontend Development (Next.js)

* **Mobile-First UI:** Build the UI using Tailwind CSS, focusing on a clean, WhatsApp-like chat interface since most Indian users will access it via mobile.
* **Onboarding Flow:** Create the landing page, "Start a Session" button, and a generated shareable link component.
* **Chat Interface:** Implement real-time or polling-based chat updates for the private intake rooms.
* **Joint View:** Build the dashboard that reveals the AI's NVC-translated summary and suggested resolutions.

### Week 4: Integration, Testing & Deployment

* **End-to-End Testing:** Simulate disputes (e.g., household chores, in-law boundaries) to test the AI's response quality and ensure state syncs between Next.js and FastAPI.
* **Safety Guardrails:** Implement checks to detect severe toxicity or self-harm keywords, triggering a hard stop and providing helpline numbers.
* **Deployment:** Deploy Next.js to Vercel and FastAPI to a platform like Render, Railway, or Google Cloud Run.

---

## 5. Sample Backend Code (FastAPI + Gemini)

Here is a foundational snippet of how your FastAPI endpoint will interact with the Gemini API using the latest Google GenAI SDK.

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

app = FastAPI()

# Initialize the Gemini Client
# Automatically picks up GEMINI_API_KEY from environment variables
client = genai.Client()

class ChatRequest(BaseModel):
    user_input: str
    context: str # e.g., "User A complaining about household chores"

# Define the Indian-Context System Prompt
SYSTEM_INSTRUCTION = """
You are an expert, culturally fluent personal conflict mediator for an Indian demographic. 
Your goal is to de-escalate tension. You understand Hinglish, joint-family dynamics, and societal pressures. 
Translate accusatory language into underlying emotional needs using Non-Violent Communication.
"""

@app.post("/api/mediate")
async def mediate_conflict(request: ChatRequest):
    try:
        # Call Gemini using gemini-3.5-flash-lite for speed and reasoning
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=f"Context: {request.context}\nUser Input: {request.user_input}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.4, # Keep it grounded and analytical
            )
        )
        
        return {"response": response.text}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

```