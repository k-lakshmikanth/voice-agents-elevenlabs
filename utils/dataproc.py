"""
Webhook Data Processing Utilities
Extracts and formats data from ElevenLabs webhook payloads
"""

from typing import Dict, List, Any, Optional
from datetime import datetime

def extract_transcript_data(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and format transcript data from webhook
    
    Returns:
        Dict containing formatted transcript with metadata
    """
    data = webhook_data.get('data', {})
    transcript_raw = data.get('transcript', [])
    
    # Format transcript for display
    formatted_transcript = []
    for entry in transcript_raw:
        formatted_entry = {
            'role': entry.get('role', 'unknown'),
            'message': entry.get('message', ''),
            'time_in_call_secs': entry.get('time_in_call_secs', 0),
            'interrupted': entry.get('interrupted', False),
            'source_medium': entry.get('source_medium', 'unknown')
        }
        
        # Only include non-null messages
        if formatted_entry['message']:
            formatted_transcript.append(formatted_entry)
    
    return {
        'conversation_id': data.get('conversation_id'),
        'agent_id': data.get('agent_id'),
        'transcript': formatted_transcript,
        'message_count': len(formatted_transcript),
        'raw_transcript': transcript_raw  # Include raw data for debugging
    }

def extract_call_statistics(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract call statistics from webhook data
    
    Returns:
        Dict containing call metrics and statistics
    """
    data = webhook_data.get('data', {})
    metadata = data.get('metadata', {})
    charging = metadata.get('charging', {})
    
    # Calculate costs in dollars (from credits)
    call_cost_dollars = charging.get('call_charge', 0) / 100000  # Convert from credits
    llm_cost_dollars = charging.get('llm_charge', 0) / 100000
    total_cost_dollars = metadata.get('cost', 0) / 100000
    
    # Extract LLM usage details
    llm_usage = charging.get('llm_usage', {})
    llm_details = {}
    
    for generation_type in ['irreversible_generation', 'initiated_generation']:
        if generation_type in llm_usage:
            models = llm_usage[generation_type].get('model_usage', {})
            for model_name, usage in models.items():
                if model_name not in llm_details:
                    llm_details[model_name] = {
                        'total_input_tokens': 0,
                        'total_output_tokens': 0,
                        'total_cost': 0
                    }
                
                input_data = usage.get('input', {})
                output_data = usage.get('output_total', {})
                
                llm_details[model_name]['total_input_tokens'] += input_data.get('tokens', 0)
                llm_details[model_name]['total_output_tokens'] += output_data.get('tokens', 0)
                llm_details[model_name]['total_cost'] += input_data.get('price', 0) + output_data.get('price', 0)
    
    return {
        'call_duration_secs': metadata.get('call_duration_secs', 0),
        'call_duration_formatted': format_duration(metadata.get('call_duration_secs', 0)),
        'start_time': datetime.fromtimestamp(metadata.get('start_time_unix_secs', 0)).isoformat() if metadata.get('start_time_unix_secs') else None,
        'termination_reason': metadata.get('termination_reason', 'Unknown'),
        'main_language': metadata.get('main_language', 'Unknown'),
        'costs': {
            'total_cost_dollars': round(total_cost_dollars, 4),
            'call_cost_dollars': round(call_cost_dollars, 4),
            'llm_cost_dollars': round(llm_cost_dollars, 4),
            'total_cost_credits': metadata.get('cost', 0),
            'call_cost_credits': charging.get('call_charge', 0),
            'llm_cost_credits': charging.get('llm_charge', 0)
        },
        'llm_usage': llm_details,
        'features_used': extract_features_used(metadata.get('features_usage', {}))
    }

def extract_analysis_data(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract analysis data including summary and collected data
    
    Returns:
        Dict containing analysis results
    """
    data = webhook_data.get('data', {})
    analysis = data.get('analysis', {})
    
    # Extract data collection results
    collected_data = {}
    data_collection = analysis.get('data_collection_results', {})
    
    for key, item in data_collection.items():
        collected_data[key] = {
            'value': item.get('value'),
            'type': item.get('json_schema', {}).get('type', 'unknown'),
            'description': item.get('json_schema', {}).get('description', ''),
            'rationale': item.get('rationale', '')
        }
    
    return {
        'summary': analysis.get('transcript_summary', ''),
        'call_successful': analysis.get('call_successful', 'unknown'),
        'collected_data': collected_data,
        'evaluation_results': analysis.get('evaluation_criteria_results', {})
    }

def format_duration(seconds: int) -> str:
    """Format duration from seconds to human readable format"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs}s"

def extract_features_used(features_usage: Dict[str, Any]) -> List[str]:
    """Extract list of features that were actually used"""
    used_features = []
    
    for feature, details in features_usage.items():
        if isinstance(details, dict) and details.get('used'):
            used_features.append(feature.replace('_', ' ').title())
        elif isinstance(details, bool) and details:
            used_features.append(feature.replace('_', ' ').title())
    
    return used_features

def process_post_call_webhook(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process post-call transcription webhook and extract all relevant data
    
    Returns:
        Dict containing all processed data ready for UI display
    """
    webhook_type = webhook_data.get('type', '')
    
    if webhook_type != 'post_call_transcription':
        return {
            'error': f'Unexpected webhook type: {webhook_type}',
            'raw_data': webhook_data
        }
    
    try:
        transcript_data = extract_transcript_data(webhook_data)
        statistics = extract_call_statistics(webhook_data)
        analysis = extract_analysis_data(webhook_data)
        
        return {
            'webhook_type': webhook_type,
            'timestamp': datetime.now().isoformat(),
            'conversation_id': transcript_data.get('conversation_id'),
            'agent_id': transcript_data.get('agent_id'),
            'transcript': transcript_data,
            'statistics': statistics,
            'analysis': analysis,
            'raw_data': webhook_data  # Include raw data for debugging
        }
    except Exception as e:
        return {
            'error': f'Error processing webhook: {str(e)}',
            'raw_data': webhook_data
        }

def get_formatted_transcript_text(transcript_data: List[Dict[str, Any]]) -> str:
    """
    Convert transcript data to formatted text
    
    Returns:
        Formatted transcript as text string
    """
    lines = []
    for entry in transcript_data:
        time = format_duration(entry.get('time_in_call_secs', 0))
        role = entry.get('role', 'unknown').upper()
        message = entry.get('message', '')
        
        if message:
            lines.append(f"[{time}] {role}: {message}")
    
    return "\n\n".join(lines)

def extract_key_patient_info(collected_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key patient information for quick reference
    
    Returns:
        Dict with key patient details
    """
    return {
        'patient_name': collected_data.get('patient_name', {}).get('value', 'Unknown'),
        'patient_dob': collected_data.get('patient_dob', {}).get('value', 'Unknown'),
        'primary_diagnosis': collected_data.get('primary_diagnosis', {}).get('value', 'Unknown'),
        'comorbidities': collected_data.get('comorbidities', {}).get('value', 'None'),
        'transportation_needed': collected_data.get('transportation_assistance', {}).get('value', False)
    }