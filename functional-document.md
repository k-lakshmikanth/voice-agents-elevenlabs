# Voice Agents

**ElevenLabs** is the engine powering our voice agents. While traditional systems often sound robotic and act strictly as text-readers, ElevenLabs provides a complete "Conversational AI" platform. It combines three critical capabilities into one seamless experience **Listening (STT)**, **Thinking (LLM)** , and **Speaking (TTS)**.

### Dynamic Variables

Placeholders in the prompt template (for example, `{{PATIENT_NAME}}`, `{{APPOINTMENT_DATE}}`) are replaced at call start using variables provided in the call-initiator socket request.

---

## Managing the Conversations
### 1. Session Management
When a user initiates a call from the dashboard, the backend creates a unique session for that interaction. This session serves as the system of record for:

- The agent configuration used for the call  
- The conversation (call) the session maps to  
- The current state (e.g., active, completed, error)  
- All metadata and artifacts collected throughout the interaction  

This session-based “room” model prevents cross-talk across concurrent calls by isolating events, state, and outputs within the correct session.

### 2. Webhooks
Because ElevenLabs executes the conversation externally, the backend depends on webhook callbacks to receive authoritative updates and final results. The webhook endpoint:

- Receives event notifications from ElevenLabs  
- Associates each event with the correct session  
- Produces a reliable post-call record (e.g., final transcript, summary, and analytics such as duration and cost)  
- Maintains a traceable, session-scoped history for auditing and debugging  

After the final webhook is received, the backend can run additional analysis to enrich the dataset (for example, tagging transcript messages by conversation stage).

### 3. Real-Time Bridge
To support live monitoring, the system maintains a real-time communication channel between the dashboard and the backend. The dashboard subscribes to the session’s “room,” ensuring it receives updates only for the relevant call.

As webhook events arrive, the backend forwards key updates through this real-time channel so the UI can reflect progress immediately without requiring a page refresh.

---

## System Architecture Diagram

```text
         USER (Patient/Staff)
             │
             │  Voice Input 
             ▼
+-----------------------------+
|        The Frontend         |────────────────────────┐
+-----------------------------+                        │
             │ ▲                                       │
             │ │  Audio Stream (WebSocket)             │
             │ │                                       │
             ▼ │                                       │
+-----------------------------+                        │
|         ELEVENLABS          |                        │
+-----------------------------+                        │
             │                                         │
             │  Webhook Events (Async)                 │  Real-time
             │                                         │    Status
             ▼                                         │    Updates
+-----------------------------+                        │
|        The Manager          |◄───────────────────────┘
+-----------------------------+
             │
             ▼
    [ Analytics & Logs ]
```