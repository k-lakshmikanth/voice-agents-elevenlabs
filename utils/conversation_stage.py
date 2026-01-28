import json
from openai import OpenAI
from pydantic import BaseModel
from typing import List, Literal, Optional

# Define the conversation stages as a literal type
ConversationStage = Literal[
    "Greeting & Identification",
    "Recipient Verification", 
    "Purpose of Call",
    "Clinical Summary",
    "Authorization Details",
    "Administrative Note",
    "Contact Confirmation",
    "Closing"
]

# Define the structure for a classified message
class ClassifiedMessage(BaseModel):
    interrupted: bool
    message: str
    role: str
    source_medium: Optional[str]
    time_in_call_secs: int
    conversation_stage: ConversationStage

# Define the structure for the full transcript
class ClassifiedTranscript(BaseModel):
    message_count: int
    session_id: str
    transcript: List[ClassifiedMessage]

def classify_conversation_stages(transcript_data: dict) -> dict:
    """
    Classify each message in the transcript by conversation stage using OpenAI's structured output.
    """
    client = OpenAI()  # Make sure to set your OPENAI_API_KEY environment variable
    
    # Convert the transcript to a readable format for the AI
    messages_text = ""
    for i, msg in enumerate(transcript_data["transcript"]):
        role = "Agent" if msg["role"] == "agent" else "User"
        messages_text += f"{i+1}. {role}: {msg['message']}\n"
    
    # Create the prompt
    prompt = f"""
    You are analyzing a medical authorization call transcript. Please classify each message according to these conversation stages:

    1. Greeting & Identification - Initial hello, introductions, identifying who is speaking
    2. Recipient Verification - Confirming the correct patient/recipient 
    3. Purpose of Call - Explaining why the call is being made
    4. Clinical Summary - Medical details, diagnoses, conditions
    5. Authorization Details - Specific authorization numbers, services, approvals
    6. Administrative Note - Documentation, paperwork, procedural information
    7. Contact Confirmation - Verifying phone numbers, contact information
    8. Closing - Ending the call, goodbyes

    Here is the transcript:
    {messages_text}

    Please classify each message with the most appropriate conversation stage.
    """
    
    # Make the API call with structured output
    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",  # Use gpt-4o or gpt-4o-mini for structured outputs
        messages=[
            {"role": "system", "content": "You are a medical call transcript analyzer. Classify each message by conversation stage."},
            {"role": "user", "content": prompt}
        ],
        response_format=ClassifiedTranscript
    )
    
    # Return the classified transcript
    return response.choices[0].message.parsed.model_dump()

