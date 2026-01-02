"""
LLM Output Handler - Safe access and normalization layer for LLM outputs.

CORE PRINCIPLE (Non-Negotiable):
    LLM output is INTERNAL data, never UI data.
    LLM output → validate → normalize → then act

This module provides:
1. Safe access helpers (no dot access on LLM dicts)
2. Normalization layer (converts internal LLM output to UI-safe contract)
3. Internal key stripping (prevents developer-only data from reaching UI)
4. Infinite loop prevention (stops recursive clarification loops)

UI Contract (ONLY allowed format):
{
    "type": "ACTION | QUESTION | ERROR",
    "message": "Human-readable text",
    "options": [],
    "action": "optional_action_name"
}
"""

from typing import Any, Optional, List, Dict, Union


# ============================================
# INTERNAL KEYS TO STRIP (UI Protection)
# ============================================

INTERNAL_KEYS = {
    "clarification",
    "analysis",
    "reasoning",
    "confidence",
    "intent_score",
    "llm_raw",
    "debug_info",
    "model_used",
    "token_count",
    "latency_ms",
    "suggested_format",  # Internal hint, not for users
}


# ============================================
# SAFE ACCESS LAYER (MANDATORY)
# ============================================

def safe_get(data: Any, key: str, default: Any = None) -> Any:
    """
    Safely access a key from LLM output dict.
    
    NEVER use dot access on LLM outputs:
        ❌ llm_output.intent
        ✅ safe_get(llm_output, "intent")
    
    This prevents:
        - 'dict' object has no attribute ... crashes
        - AttributeError during ambiguity handling
        - Runtime crashes from missing keys
    
    Args:
        data: The LLM output dict (or any data)
        key: The key to access
        default: Value to return if key missing or data is not dict
    
    Returns:
        The value at key, or default if missing/invalid
    """
    if not isinstance(data, dict):
        return default
    return data.get(key, default)


def safe_get_nested(data: Any, *keys: str, default: Any = None) -> Any:
    """
    Safely access nested keys from LLM output.
    
    Example:
        safe_get_nested(llm_output, "split", "pages", default=[])
    
    Args:
        data: The LLM output dict
        *keys: Variable number of keys for nested access
        default: Value to return if any key is missing
    
    Returns:
        The nested value, or default if path doesn't exist
    """
    current = data
    for key in keys:
        current = safe_get(current, key)
        if current is None:
            return default
    return current if current is not None else default


# ============================================
# INTERNAL KEY STRIPPING (UI Protection)
# ============================================

def strip_internal_keys(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove internal/developer-only keys before sending to UI.
    
    This prevents:
        - Markdown leaks in UI
        - Developer-only text shown to users
        - Internal reasoning exposed
    
    Args:
        data: Dict that may contain internal keys
    
    Returns:
        Clean dict safe for UI consumption
    """
    if not isinstance(data, dict):
        return data
    return {k: v for k, v in data.items() if k not in INTERNAL_KEYS}


def strip_internal_recursive(data: Any) -> Any:
    """
    Recursively strip internal keys from nested structures.
    
    Args:
        data: Any data structure (dict, list, or primitive)
    
    Returns:
        Cleaned data structure
    """
    if isinstance(data, dict):
        return {
            k: strip_internal_recursive(v) 
            for k, v in data.items() 
            if k not in INTERNAL_KEYS
        }
    elif isinstance(data, list):
        return [strip_internal_recursive(item) for item in data]
    return data


# ============================================
# NORMALIZATION LAYER (UI Boundary)
# ============================================

class UIResponseType:
    """Response types for UI contract"""
    ACTION = "ACTION"
    QUESTION = "QUESTION"
    ERROR = "ERROR"


def normalize_for_ui(
    llm_output: Dict[str, Any],
    session: Any = None,
    override_message: Optional[str] = None,
    override_options: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Convert internal LLM output into UI-safe contract.
    
    This is the ONLY format that should reach the UI:
    {
        "type": "ACTION | QUESTION | ERROR",
        "message": "Human-readable text",
        "options": [],
        "action": "optional_action_name"
    }
    
    ✔ Does NOT infer intent
    ✔ Does NOT change ambiguity logic
    ✔ Does NOT affect token handling
    
    Args:
        llm_output: Raw LLM output dict
        session: Optional session object for context
        override_message: Optional message to use instead of LLM output
        override_options: Optional options to use instead of LLM output
    
    Returns:
        UI-safe normalized response dict
    """
    needs_clarification = safe_get(llm_output, "needs_clarification", False)
    action = safe_get(llm_output, "action")
    operation_type = safe_get(llm_output, "operation_type")
    
    # Get message and options from various sources
    message = override_message
    options = override_options or []
    
    if not message:
        # Try to get from LLM output
        message = safe_get(llm_output, "question")
        if not message and session:
            message = getattr(session, "last_question", None) or getattr(session, "pending_question", None)
    
    if not options:
        options = safe_get(llm_output, "options", [])
        if not options and session:
            options = getattr(session, "last_options", None) or getattr(session, "pending_options", None) or []
    
    # Ensure options is always a list
    if not isinstance(options, list):
        options = []
    
    # Determine response type
    if needs_clarification:
        return {
            "type": UIResponseType.QUESTION,
            "message": message or "Please choose an option:",
            "options": options
        }
    
    if action or operation_type:
        return {
            "type": UIResponseType.ACTION,
            "message": "Processing your request…",
            "action": action or operation_type
        }
    
    return {
        "type": UIResponseType.ERROR,
        "message": message or "I couldn't understand that. Please try again."
    }


def create_question_response(
    message: str,
    options: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a QUESTION type response for UI.
    
    Args:
        message: The question to ask the user
        options: Optional list of clickable options
    
    Returns:
        UI-safe QUESTION response
    """
    return {
        "type": UIResponseType.QUESTION,
        "message": message,
        "options": options or []
    }


def create_action_response(
    action: str,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an ACTION type response for UI.
    
    Args:
        action: The action being performed
        message: Optional status message
    
    Returns:
        UI-safe ACTION response
    """
    return {
        "type": UIResponseType.ACTION,
        "message": message or "Processing your request…",
        "action": action
    }


def create_error_response(
    message: str,
    options: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create an ERROR type response for UI.
    
    Args:
        message: The error message for the user
        options: Optional suggested alternatives
    
    Returns:
        UI-safe ERROR response
    """
    response = {
        "type": UIResponseType.ERROR,
        "message": message
    }
    if options:
        response["options"] = options
    return response


# ============================================
# INFINITE LOOP PREVENTION
# ============================================

def check_clarification_loop(
    llm_output: Dict[str, Any],
    session: Any
) -> Optional[Dict[str, Any]]:
    """
    Check and prevent infinite clarification loops.
    
    Rule: If clarification was already asked once, force user selection.
    
    Args:
        llm_output: Current LLM output
        session: Session object with history
    
    Returns:
        Error response if loop detected, None otherwise
    """
    if session is None:
        return None
    
    # Get last response type from session
    last_response_type = getattr(session, "last_response_type", None)
    needs_clarification = safe_get(llm_output, "needs_clarification", False)
    
    if last_response_type == UIResponseType.QUESTION and needs_clarification:
        return {
            "type": UIResponseType.ERROR,
            "message": "Please select one of the options above.",
            "options": getattr(session, "last_options", None) or getattr(session, "pending_options", None) or []
        }
    
    return None


def update_session_response_type(session: Any, response_type: str) -> None:
    """
    Update session with the current response type for loop detection.
    
    Args:
        session: Session object to update
        response_type: The response type being sent (ACTION/QUESTION/ERROR)
    """
    if session is not None:
        session.last_response_type = response_type


# ============================================
# VALIDATION HELPERS
# ============================================

def validate_llm_output(llm_output: Any) -> bool:
    """
    Validate that LLM output is properly structured.
    
    Args:
        llm_output: The raw LLM output
    
    Returns:
        True if valid, False otherwise
    """
    if not isinstance(llm_output, dict):
        return False
    
    # Must have either operation_type or needs_clarification
    has_operation = safe_get(llm_output, "operation_type") is not None
    has_clarification = safe_get(llm_output, "needs_clarification", False)
    has_multi_op = safe_get(llm_output, "is_multi_operation", False)
    
    return has_operation or has_clarification or has_multi_op


def extract_options_safely(llm_output: Dict[str, Any]) -> List[str]:
    """
    Safely extract options from LLM output.
    
    Args:
        llm_output: The LLM output dict
    
    Returns:
        List of options (empty list if none)
    """
    options = safe_get(llm_output, "options", [])
    if not isinstance(options, list):
        return []
    # Ensure all options are strings
    return [str(opt) for opt in options if opt is not None]


def extract_operation_type(llm_output: Dict[str, Any]) -> Optional[str]:
    """
    Safely extract operation type from LLM output.
    
    Args:
        llm_output: The LLM output dict
    
    Returns:
        Operation type string or None
    """
    op_type = safe_get(llm_output, "operation_type")
    if isinstance(op_type, str):
        return op_type.lower().strip()
    return None


# ============================================
# UI RULES ENFORCEMENT
# ============================================

# Keys that UI MAY read
UI_ALLOWED_KEYS = {"message", "options", "type", "action", "status", "operation", "output_file"}

# Keys that UI MUST NEVER read directly
UI_FORBIDDEN_KEYS = {"intent", "clarification", "analysis", "reasoning", "confidence", "llm_raw"}


def enforce_ui_contract(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enforce UI contract by removing forbidden keys.
    
    UI must not render raw objects - only the normalized contract.
    
    Args:
        response: Response dict being sent to UI
    
    Returns:
        Cleaned response safe for UI
    """
    if not isinstance(response, dict):
        return {"type": UIResponseType.ERROR, "message": "Invalid response format"}
    
    # Remove any forbidden keys
    cleaned = {k: v for k, v in response.items() if k not in UI_FORBIDDEN_KEYS}
    
    # Ensure required keys exist
    if "type" not in cleaned:
        cleaned["type"] = UIResponseType.ERROR
    if "message" not in cleaned:
        cleaned["message"] = "An error occurred."
    
    return cleaned
