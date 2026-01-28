# Healthcare Agent Conversation Orchestration MVP

A scalable orchestration server for managing ElevenLabs conversational AI agents without handling audio on the server.

## Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Browser   │────▶│  Orchestration   │────▶│ ElevenLabs  │
│   Client    │◀────│     Server       │◀────│    API      │
└─────────────┘     └──────────────────┘     └─────────────┘
      │                                              │
      └──────────────Audio Stream───────────────────┘
```

- **Browser Client**: Handles audio capture/playback using ElevenLabs Web SDK
- **Orchestration Server**: Manages sessions, webhooks, and conversation state
- **ElevenLabs API**: Processes conversations and sends webhooks

## Features

- Session management for multiple concurrent conversations
- Real-time updates via WebSocket
- Webhook processing with signature verification
- Agent configuration management
- Conversation transcript tracking
- Clean separation of concerns (audio handled client-side)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file with your credentials:

```bash
ELEVENLABS_API_KEY=your_api_key_here
WEBHOOK_SECRET=wsec_4da0175bf4ecfc89ad4c909001c923a609069948c4dccf13fc1cf157b5e82b71
```

### 3. Configure Webhook URL

For local testing, use ngrok to expose your server:

```bash
ngrok http 5000
```

Then configure your ElevenLabs webhook URL to:
```
https://your-ngrok-url.ngrok.io/webhook
```

### 4. Start the Server

```bash
python conv_orchestration.py
```

### 5. Access the Client

Open your browser to `http://localhost:5000`

## Running Backend + Frontend

The frontend is served directly by the Flask backend. There is no separate frontend dev server.

### Local (single process)

```bash
python conv_orchestration.py
```

### Production-style (Gunicorn + eventlet)

```bash
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 conv_orchestration:app
```

## API Endpoints

### Health Check
```
GET /api/health
```

### Get Available Agents
```
GET /api/agents
```

### Create Session
```
POST /api/sessions
Body: { "agent_key": "clara" }
```

### Get Session Details
```
GET /api/sessions/{session_id}
```

### Get Transcript
```
GET /api/sessions/{session_id}/transcript
```

### Webhook Endpoint
```
POST /webhook
Headers: XI-Signature-256
```

## WebSocket Events

### Client → Server
- `join_session`: Join a conversation session
- `leave_session`: Leave a conversation session
- `conversation_started`: Notify when ElevenLabs conversation starts

### Server → Client
- `webhook_update`: Real-time webhook data
- `session_joined`: Confirmation of joining session
- `conversation_update`: Conversation status updates

## Project Structure

```
.
├── orchestration_server.py  # Main server application
├── client.html             # Web client interface
├── requirements.txt        # Python dependencies
├── .env                   # Environment configuration
└── README.md              # Documentation
```

## Scaling Considerations

### Current Implementation
- In-memory session storage
- Single server instance
- Synchronous webhook processing

### Production Upgrades
1. **Session Storage**: Replace in-memory dict with Redis
2. **Queue System**: Add RabbitMQ/Redis for webhook processing
3. **Load Balancing**: Deploy multiple server instances
4. **Database**: Add PostgreSQL for conversation history
5. **Monitoring**: Add logging aggregation and metrics

## Security Features

- Webhook signature verification
- CORS configuration
- Environment-based secrets
- Session isolation

## Development Tips

1. **Testing Webhooks**: Use ngrok for local webhook testing
2. **Debug Mode**: Check console logs in browser and server
3. **Session Cleanup**: Implement TTL for abandoned sessions
4. **Error Handling**: All errors are logged and returned as JSON

## Next Steps

1. Add Redis for distributed session storage
2. Implement conversation history persistence
3. Add authentication/authorization
4. Create admin dashboard
5. Add metrics and monitoring
6. Implement rate limiting
7. Add conversation analytics

## Troubleshooting

### Client can't connect to WebSocket
- Check CORS configuration
- Verify WebSocket URL in client config

### Webhooks not received
- Verify ngrok is running
- Check webhook URL in ElevenLabs dashboard
- Verify webhook secret matches

### Audio not working
- Ensure HTTPS for production (required for browser audio)
- Check browser console for permission errors
- Verify ElevenLabs API key is valid
