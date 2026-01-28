"""
Conversation Orchestration Server
Manages ElevenLabs conversational AI sessions without handling audio directly
"""

import os
import uuid
import hmac
import hashlib
import logging
from datetime import datetime
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
import requests
from dotenv import load_dotenv

#Side Async Functions (Transcript -> Conversation Stage Management, Transcript -> Email Summary)
from utils.conversation_stage import classify_conversation_stages

# Import webhook processing utilities
from utils.dataproc import (
    process_post_call_webhook,
    extract_transcript_data,
    extract_call_statistics,
    extract_analysis_data,
    extract_key_patient_info
)

# Load environment variables
load_dotenv()

# Configuration
class Config:
    ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'wsec_4da0175bf4ecfc89ad4c909001c923a609069948c4dccf13fc1cf157b5e82b71')
    SERVER_PORT = int(os.getenv('SERVER_PORT', 5000))
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    ELEVENLABS_API_URL = 'https://api.elevenlabs.io/v1'

# Setup logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'development-secret-key')

# ngrok wildcard requires regex=True
CORS(app, 
     origins=[r"https://.*\.ngrok-free\.app", "http://localhost:4200","https://zyter-trucare-da4d9.web.app"],
     allow_headers=["Content-Type", "Authorization", "ngrok-skip-browser-warning"],
     expose_headers=["Content-Length", "X-JSON"],
     supports_credentials=True,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     send_wildcard=False,
     vary_header=True)

socketio = SocketIO(app, cors_allowed_origins=[
    "http://localhost:4200", 
    "https://*.ngrok-free.app",
    "https://zyter-trucare-da4d9.web.app"
])

# OPTIONS handler for preflight (recommended)
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", request.headers.get('Origin', '*'))
        response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization, ngrok-skip-browser-warning")
        response.headers.add("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        response.headers.add("Access-Control-Allow-Credentials", "true")
        return response, 200


# Data models
class ConversationStatus(Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"

@dataclass
class ConversationSession:
    session_id: str
    agent_id: str
    conversation_id: Optional[str] = None
    status: ConversationStatus = ConversationStatus.INITIALIZING
    created_at: datetime = None
    updated_at: datetime = None
    metadata: Dict[str, Any] = None
    webhook_data: list = None
    processed_data: Dict[str, Any] = None  # New field for processed webhook data
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = self.created_at
        if self.metadata is None:
            self.metadata = {}
        if self.webhook_data is None:
            self.webhook_data = []
        if self.processed_data is None:
            self.processed_data = {}

# Session storage (use Redis in production)
sessions: Dict[str, ConversationSession] = {}

# Agent configuration storage
agent_configs = {
    "clara": {
        "agent_id": "agent_01jz0h1rqperc8z03gsvkprmsw",
        "name": "Clara",
        "role": "Patient Intake Coordinator"
    },
    "marcus": {
        "agent_id": "agent_01jz2jh0cdekqv8j35hqpw9wbb",
        "name": "Marcus",
        "role": "Authorization Coordinator"
    },
    "sarah": {
        "agent_id": "agent_01jz2n3j1dfnrbj2vpdpghkbm3",
        "name": "Sarah",
        "role": "Patient Educator"
    },
        "david": {                                           # ← ADD THIS
        "agent_id": "agent_01k0rvs4awfsn8vj6n4awffc2f",  # ← NEW AGENT ID
        "name": "David",
        "role": "Extended Stay Authorization Coordinator"
    }
}

# Webhook verification
def verify_webhook_signature(request_obj) -> bool:
    """Verify webhook signature from ElevenLabs"""
    try:
        signature = request_obj.headers.get('elevenlabs-signature')
        if not signature:
            logger.warning("Missing webhook signature")
            return False
        
        # Get raw payload as bytes
        payload = request_obj.get_data()

        # Compute HMAC SHA256 using your secret
        expected_signature = hmac.new(
            Config.WEBHOOK_SECRET.encode('utf-8'),
            payload,
            hashlib.sha256
        ).hexdigest()

        # Use constant-time comparison
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning("Invalid webhook signature")
            return True
            # return False
        
        return True
    
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'sessions_active': len([s for s in sessions.values() if s.status == ConversationStatus.ACTIVE])
    })

@app.route('/api/agents', methods=['GET'])
def get_agents():
    """Get available agents"""
    return jsonify({
        'agents': [
            {
                'key': key,
                'name': config['name'],
                'role': config['role'],
                'agent_id': config['agent_id']
            }
            for key, config in agent_configs.items()
        ]
    })

@app.route('/api/sessions', methods=['POST'])
def create_session():
    """Create a new conversation session"""
    data = request.json
    agent_key = data.get('agent_key')
    
    if agent_key not in agent_configs:
        return jsonify({'error': 'Invalid agent key'}), 400
    
    session_id = str(uuid.uuid4())
    agent_config = agent_configs[agent_key]
    
    session = ConversationSession(
        session_id=session_id,
        agent_id=agent_config['agent_id'],
        metadata={
            'agent_name': agent_config['name'],
            'agent_role': agent_config['role'],
            'client_ip': request.remote_addr
        }
    )
    
    sessions[session_id] = session
    
    logger.info(f"Created session {session_id} for agent {agent_key}")
    
    return jsonify({
        'session_id': session_id,
        'agent': {
            'name': agent_config['name'],
            'role': agent_config['role']
        },
        'websocket_url': f"ws://localhost:{Config.SERVER_PORT}",
        'status': session.status.value
    })

@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    """Get session details"""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    return jsonify({
        'session_id': session.session_id,
        'status': session.status.value,
        'agent_id': session.agent_id,
        'conversation_id': session.conversation_id,
        'created_at': session.created_at.isoformat(),
        'updated_at': session.updated_at.isoformat(),
        'metadata': session.metadata,
        'webhook_count': len(session.webhook_data),
        'processed_data': session.processed_data  # Include processed data
    })

@app.route('/api/sessions/<session_id>/transcript', methods=['GET'])
def get_transcript(session_id):
    """Get conversation transcript"""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    # Check if we have processed transcript data
    if session.processed_data and 'transcript' in session.processed_data:
        return jsonify({
            'session_id': session_id,
            'transcript': session.processed_data['transcript'].get('transcript', []),
            'message_count': session.processed_data['transcript'].get('message_count', 0)
        })
    
    # Fallback to raw webhook data
    transcript = []
    for webhook in session.webhook_data:
        if webhook.get('type') == 'conversation.update':
            data = webhook.get('data', {})
            if 'transcript' in data:
                transcript.extend(data['transcript'])
    
    return jsonify({
        'session_id': session_id,
        'transcript': transcript,
        'message_count': len(transcript)
    })

@app.route('/api/sessions/<session_id>/staged-transcript', methods=['GET'])
def get_staged_transcript(session_id):
    """Get staged conversation transcript"""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    if session.processed_data and 'classified_transcript' in session.processed_data:
        return jsonify({
            'session_id': session_id,
            'transcript': session.processed_data['classified_transcript'].get('transcript',[]),
            'message_count': session.processed_data['classified_transcript'].get('message_count', 0)
        })
    
    classified_transcript = []
    return jsonify({
        'session_id': session_id,
        'transcript': classified_transcript,
        'message_count': len(classified_transcript)
    })

# Webhook endpoint
@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle ElevenLabs webhooks"""
    if not verify_webhook_signature(request):
        logger.warning("Invalid webhook signature")
        return jsonify({'error': 'Invalid signature'}), 401
    
    try:
        webhook_data = request.json
        webhook_type = webhook_data.get('type')
        conversation_id = webhook_data.get('data', {}).get('conversation_id')
        
        logger.info(f"Received webhook: {webhook_type} for conversation {conversation_id}")
        
        # Find session by conversation_id
        session = None
        for sess in sessions.values():
            if sess.conversation_id == conversation_id:
                session = sess
                break
        
        # ENHANCED FALLBACK: If no session found, try to match by agent_id
        if not session and webhook_type == 'post_call_transcription':
            agent_id = webhook_data.get('data', {}).get('agent_id')
            if agent_id:
                logger.warning(f"No session found for conversation {conversation_id}, attempting fallback match by agent_id {agent_id}")
                
                # Debug: Log all sessions
                logger.info("Current sessions:")
                for sess_id, sess in sessions.items():
                    logger.info(f"  - Session {sess_id}: agent_id={sess.agent_id}, status={sess.status.value}, created={sess.created_at}")
                
                # Find most recent active/initializing session for this agent
                matching_sessions = [
                    sess for sess in sessions.values() 
                    if sess.agent_id == agent_id and sess.status in [ConversationStatus.ACTIVE, ConversationStatus.INITIALIZING]
                ]
                
                if matching_sessions:
                    # Use the most recent session
                    session = max(matching_sessions, key=lambda s: s.created_at)
                    
                    # Link the conversation_id to this session
                    session.conversation_id = conversation_id
                    session.status = ConversationStatus.ACTIVE
                    
                    logger.info(f"FALLBACK SUCCESS: Linked conversation {conversation_id} to session {session.session_id} based on agent_id {agent_id}")
                else:
                    # Try ANY recent session if exact agent match fails
                    recent_sessions = [
                        sess for sess in sessions.values() 
                        if sess.status in [ConversationStatus.ACTIVE, ConversationStatus.INITIALIZING]
                        and (datetime.utcnow() - sess.created_at).total_seconds() < 300  # Within last 5 minutes
                    ]
                    
                    if recent_sessions:
                        session = max(recent_sessions, key=lambda s: s.created_at)
                        logger.warning(f"FALLBACK: Using most recent session {session.session_id} (agent mismatch: expected {agent_id}, got {session.agent_id})")
                        
                        # Link the conversation_id to this session
                        session.conversation_id = conversation_id
                        session.status = ConversationStatus.ACTIVE
                    else:
                        logger.error(f"FALLBACK FAILED: No active sessions found for agent_id {agent_id}")
        
        if session:
            # Store raw webhook data
            session.webhook_data.append({
                'type': webhook_type,
                'timestamp': datetime.utcnow().isoformat(),
                'data': webhook_data.get('data', {})
            })
            session.updated_at = datetime.utcnow()
            
            # Process post-call transcription webhook
            if webhook_type == 'post_call_transcription':
                try:
                    # Process the webhook data using utils
                    processed_data = process_post_call_webhook(webhook_data)
                    
                    # Store processed data in session
                    session.processed_data = processed_data
                    
                    # Classify conversation stages
                    if 'transcript' in processed_data:
                        try:
                            classified_transcript = classify_conversation_stages(processed_data['transcript'])
                            session.processed_data['classified_transcript'] = classified_transcript
                            logger.info(f"Auto-classified conversation stages for session {session.session_id}")
                        except Exception as e:
                            logger.error(f"Error auto-classifying stages: {str(e)}")
                    
                    # Log key information
                    logger.info(f"Processed post-call data for session {session.session_id}:")
                    logger.info(f"  - Conversation ID: {processed_data.get('conversation_id')}")
                    logger.info(f"  - Message count: {processed_data.get('transcript', {}).get('message_count', 0)}")
                    logger.info(f"  - Call duration: {processed_data.get('statistics', {}).get('call_duration_formatted', 'N/A')}")
                    logger.info(f"  - Total cost: ${processed_data.get('statistics', {}).get('costs', {}).get('total_cost_dollars', 0):.4f}")
                    
                    # Extract key patient info if available
                    if 'analysis' in processed_data and 'collected_data' in processed_data['analysis']:
                        patient_info = extract_key_patient_info(processed_data['analysis']['collected_data'])
                        logger.info(f"  - Patient: {patient_info.get('patient_name', 'Unknown')}")
                        logger.info(f"  - Primary diagnosis: {patient_info.get('primary_diagnosis', 'Unknown')}")
                    
                except Exception as e:
                    logger.error(f"Error processing post-call webhook: {str(e)}")
                    session.processed_data['processing_error'] = str(e)
            
            # Update session status based on webhook type
            if webhook_type == 'conversation.completed' or webhook_type == 'post_call_transcription':
                session.status = ConversationStatus.COMPLETED
            elif webhook_type == 'conversation.error':
                session.status = ConversationStatus.ERROR
            
            # Emit to WebSocket room with processed data summary
            emit_data = {
                'type': webhook_type,
                'session_id': session.session_id,
                'data': webhook_data.get('data', {})
            }
            
            # Add processed data summary for post-call transcription
            if webhook_type == 'post_call_transcription' and session.processed_data:
                emit_data['summary'] = {
                    'message_count': session.processed_data.get('transcript', {}).get('message_count', 0),
                    'call_duration': session.processed_data.get('statistics', {}).get('call_duration_formatted', 'N/A'),
                    'total_cost': session.processed_data.get('statistics', {}).get('costs', {}).get('total_cost_dollars', 0),
                    'call_summary': session.processed_data.get('analysis', {}).get('summary', '')[:200] + '...' if len(session.processed_data.get('analysis', {}).get('summary', '')) > 200 else session.processed_data.get('analysis', {}).get('summary', '')
                }
            
            socketio.emit('webhook_update', emit_data, room=session.session_id)
            
            logger.info(f"Processed webhook for session {session.session_id}")
        else:
            logger.warning(f"No session found for conversation {conversation_id}")
        
        return jsonify({'status': 'processed'})
        
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({'error': 'Processing failed'}), 500

# New endpoint to get processed call data
@app.route('/api/sessions/<session_id>/call-summary', methods=['GET'])
def get_call_summary(session_id):
    """Get processed call summary data"""
    session = sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Session not found'}), 404
    
    if not session.processed_data:
        return jsonify({'error': 'No processed data available yet'}), 404
    
    # Return a clean summary
    summary = {
        'session_id': session_id,
        'conversation_id': session.conversation_id,
        'status': session.status.value,
        'timestamp': session.processed_data.get('timestamp'),
        'transcript_summary': {
            'message_count': session.processed_data.get('transcript', {}).get('message_count', 0),
            'agent_id': session.processed_data.get('agent_id')
        },
        'call_statistics': {
            'duration': session.processed_data.get('statistics', {}).get('call_duration_formatted'),
            'start_time': session.processed_data.get('statistics', {}).get('start_time'),
            'termination_reason': session.processed_data.get('statistics', {}).get('termination_reason'),
            'costs': session.processed_data.get('statistics', {}).get('costs', {}),
            'features_used': session.processed_data.get('statistics', {}).get('features_used', [])
        },
        'analysis': {
            'summary': session.processed_data.get('analysis', {}).get('summary'),
            'call_successful': session.processed_data.get('analysis', {}).get('call_successful'),
            'collected_data_count': len(session.processed_data.get('analysis', {}).get('collected_data', {}))
        }
    }
    
    # Add patient info if available
    if 'analysis' in session.processed_data and 'collected_data' in session.processed_data['analysis']:
        summary['patient_info'] = extract_key_patient_info(session.processed_data['analysis']['collected_data'])
    
    return jsonify(summary)

# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to orchestration server'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('join_session')
def handle_join_session(data):
    """Join a conversation session room"""
    session_id = data.get('session_id')
    session = sessions.get(session_id)
    
    if not session:
        emit('error', {'message': 'Invalid session'})
        return
    
    join_room(session_id)
    session.status = ConversationStatus.ACTIVE
    
    emit('session_joined', {
        'session_id': session_id,
        'status': session.status.value
    })
    
    logger.info(f"Client {request.sid} joined session {session_id}")

@socketio.on('leave_session')
def handle_leave_session(data):
    """Leave a conversation session room"""
    session_id = data.get('session_id')
    leave_room(session_id)
    
    emit('session_left', {'session_id': session_id})
    logger.info(f"Client {request.sid} left session {session_id}")

@socketio.on('conversation_started')
def handle_conversation_started(data):
    """Handle conversation start event from client"""
    session_id = data.get('session_id')
    conversation_id = data.get('conversation_id')
    
    session = sessions.get(session_id)
    if session:
        session.conversation_id = conversation_id
        session.status = ConversationStatus.ACTIVE
        session.updated_at = datetime.utcnow()
        
        logger.info(f"Conversation {conversation_id} started for session {session_id}")
        
        # Notify other clients in the room
        emit('conversation_update', {
            'session_id': session_id,
            'conversation_id': conversation_id,
            'status': 'started'
        }, room=session_id)

# Serve static files (HTML client)
@app.route('/')
def serve_client():
    """Serve the HTML client"""
    return send_from_directory('.', 'client.html')

@app.route('/api/config')
def get_client_config():
    """Get client configuration"""
    return jsonify({
        'elevenlabs_api_key': Config.ELEVENLABS_API_KEY,
        'websocket_url': f"ws://localhost:{Config.SERVER_PORT}"
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    logger.info(f"Starting orchestration server on port {Config.SERVER_PORT}")
    logger.info("Webhook URL: http://localhost:5000/webhook")
    logger.info("Client URL: http://localhost:5000")
    
    socketio.run(app, host='0.0.0.0', port=Config.SERVER_PORT, debug=True)