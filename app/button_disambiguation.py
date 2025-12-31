"""
Button-Based Disambiguation Module

When the One-Flow Resolution cannot deterministically resolve a command,
this module generates button options for user selection.

RULES (from spec):
- Present top 3-5 actions when unclear
- User selects via buttons
- Execute chosen pipeline immediately
- Prefer action over questions
- Never expose technical errors
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================
# BUTTON TYPES
# ============================================

class ButtonType(str, Enum):
    """Button types for disambiguation"""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    CANCEL = "cancel"


@dataclass
class ActionButton:
    """Represents a single action button"""
    id: str
    label: str
    description: Optional[str] = None
    pipeline: List[str] = field(default_factory=list)
    button_type: ButtonType = ButtonType.SECONDARY
    target_format: Optional[str] = None
    target_size_mb: Optional[float] = None


@dataclass
class DisambiguationResponse:
    """Response containing button options"""
    message: str
    buttons: List[ActionButton] = field(default_factory=list)
    show_cancel: bool = True
    context_hint: Optional[str] = None


# ============================================
# COMMON ACTION SETS
# ============================================

# Pre-defined action sets by context
PDF_ACTIONS = [
    ActionButton(
        id="compress_pdf",
        label="🗜️ Compress PDF",
        description="Reduce file size",
        pipeline=["compress"],
        button_type=ButtonType.PRIMARY
    ),
    ActionButton(
        id="convert_to_docx",
        label="📄 Convert to DOCX",
        description="Editable Word document",
        pipeline=["convert"],
        target_format="docx"
    ),
    ActionButton(
        id="ocr_pdf",
        label="🔍 OCR (Extract Text)",
        description="Make text searchable",
        pipeline=["ocr"]
    ),
    ActionButton(
        id="split_pdf",
        label="✂️ Split Pages",
        description="Separate into individual pages",
        pipeline=["split"]
    ),
    ActionButton(
        id="merge_pdfs",
        label="📑 Merge PDFs",
        description="Combine multiple files",
        pipeline=["merge"]
    ),
    ActionButton(
        id="add_watermark",
        label="💧 Add Watermark",
        description="Add text watermark",
        pipeline=["watermark"]
    ),
    ActionButton(
        id="add_page_numbers",
        label="#️⃣ Add Page Numbers",
        description="Number each page",
        pipeline=["page-numbers"]
    ),
    ActionButton(
        id="rotate_pdf",
        label="🔄 Rotate Pages",
        description="Rotate 90°, 180°, or 270°",
        pipeline=["rotate"]
    ),
    ActionButton(
        id="flatten_pdf",
        label="📋 Flatten PDF",
        description="Flatten form fields",
        pipeline=["flatten"]
    ),
]

IMAGE_ACTIONS = [
    ActionButton(
        id="convert_to_pdf",
        label="📄 Convert to PDF",
        description="Create PDF from image",
        pipeline=["convert"],
        target_format="pdf",
        button_type=ButtonType.PRIMARY
    ),
    ActionButton(
        id="compress_image",
        label="🗜️ Compress Image",
        description="Reduce file size",
        pipeline=["compress"]
    ),
    ActionButton(
        id="enhance_image",
        label="✨ Enhance Image",
        description="Improve quality",
        pipeline=["enhance"]
    ),
    ActionButton(
        id="merge_to_pdf",
        label="📑 Merge Images to PDF",
        description="Combine into single PDF",
        pipeline=["merge"],
        target_format="pdf"
    ),
]

DOCX_ACTIONS = [
    ActionButton(
        id="convert_to_pdf",
        label="📄 Convert to PDF",
        description="Create PDF from document",
        pipeline=["convert"],
        target_format="pdf",
        button_type=ButtonType.PRIMARY
    ),
    ActionButton(
        id="compress_docx",
        label="🗜️ Compress",
        description="Reduce file size",
        pipeline=["compress"]
    ),
    ActionButton(
        id="add_watermark_docx",
        label="💧 Add Watermark",
        description="Add text watermark",
        pipeline=["watermark"]
    ),
]

# Size-specific actions
SIZE_ACTIONS = {
    "500kb": [
        ActionButton(
            id="compress_500kb",
            label="🗜️ Compress to 500KB",
            description="Aggressive compression",
            pipeline=["compress"],
            target_size_mb=0.5,
            button_type=ButtonType.PRIMARY
        ),
    ],
    "1mb": [
        ActionButton(
            id="compress_1mb",
            label="🗜️ Compress to 1MB",
            description="Strong compression",
            pipeline=["compress"],
            target_size_mb=1.0,
            button_type=ButtonType.PRIMARY
        ),
    ],
    "2mb": [
        ActionButton(
            id="compress_2mb",
            label="🗜️ Compress to 2MB",
            description="Moderate compression",
            pipeline=["compress"],
            target_size_mb=2.0,
            button_type=ButtonType.PRIMARY
        ),
    ],
}

# Purpose-specific actions
PURPOSE_ACTIONS = {
    "email": [
        ActionButton(
            id="optimize_email",
            label="📧 Optimize for Email",
            description="Under 10MB, good quality",
            pipeline=["compress"],
            target_size_mb=10.0,
            button_type=ButtonType.PRIMARY
        ),
    ],
    "whatsapp": [
        ActionButton(
            id="optimize_whatsapp",
            label="💬 Optimize for WhatsApp",
            description="Under 16MB",
            pipeline=["compress"],
            target_size_mb=16.0,
            button_type=ButtonType.PRIMARY
        ),
    ],
    "print": [
        ActionButton(
            id="optimize_print",
            label="🖨️ Optimize for Print",
            description="High quality, 300 DPI",
            pipeline=["enhance"],
            button_type=ButtonType.PRIMARY
        ),
    ],
}


# ============================================
# DISAMBIGUATION GENERATOR
# ============================================

class DisambiguationGenerator:
    """
    Generates button options for disambiguation
    """
    
    def __init__(self):
        self.pdf_actions = PDF_ACTIONS.copy()
        self.image_actions = IMAGE_ACTIONS.copy()
        self.docx_actions = DOCX_ACTIONS.copy()
    
    def generate(
        self,
        file_type: str,
        detected_operations: Optional[List[str]] = None,
        detected_purpose: Optional[str] = None,
        detected_size: Optional[str] = None,
        partial_match_hint: Optional[str] = None
    ) -> DisambiguationResponse:
        """
        Generate disambiguation buttons based on context.
        
        Args:
            file_type: pdf, docx, jpg, png, etc.
            detected_operations: Partially detected operations
            detected_purpose: email, whatsapp, print
            detected_size: 500kb, 1mb, 2mb
            partial_match_hint: Hint from partial matching
        
        Returns:
            DisambiguationResponse with buttons
        """
        
        buttons: List[ActionButton] = []
        message = "What would you like to do?"
        
        # Priority 1: Size-specific actions
        if detected_size and detected_size.lower() in SIZE_ACTIONS:
            buttons.extend(SIZE_ACTIONS[detected_size.lower()])
            message = f"Compress to {detected_size}?"
        
        # Priority 2: Purpose-specific actions
        elif detected_purpose and detected_purpose.lower() in PURPOSE_ACTIONS:
            buttons.extend(PURPOSE_ACTIONS[detected_purpose.lower()])
            message = f"Optimize for {detected_purpose}?"
        
        # Priority 3: File type base actions
        else:
            file_type_lower = file_type.lower()
            
            if file_type_lower == "pdf":
                buttons.extend(self.pdf_actions[:5])
            elif file_type_lower in ("jpg", "jpeg", "png", "img"):
                buttons.extend(self.image_actions[:4])
            elif file_type_lower in ("docx", "doc"):
                buttons.extend(self.docx_actions[:3])
            else:
                # Default to PDF actions
                buttons.extend(self.pdf_actions[:3])
        
        # Prioritize based on detected operations
        if detected_operations:
            buttons = self._prioritize_by_operations(buttons, detected_operations)
        
        # Ensure we have at least some buttons
        if not buttons:
            buttons = [
                ActionButton(
                    id="compress",
                    label="🗜️ Compress",
                    description="Reduce file size",
                    pipeline=["compress"],
                    button_type=ButtonType.PRIMARY
                ),
                ActionButton(
                    id="convert",
                    label="📄 Convert",
                    description="Change format",
                    pipeline=["convert"]
                ),
            ]
        
        # Mark first button as primary
        if buttons:
            buttons[0].button_type = ButtonType.PRIMARY
        
        # Add cancel button
        cancel = ActionButton(
            id="cancel",
            label="❌ Cancel",
            description="Cancel operation",
            pipeline=[],
            button_type=ButtonType.CANCEL
        )
        
        return DisambiguationResponse(
            message=message,
            buttons=buttons[:5],  # Max 5 buttons
            show_cancel=True,
            context_hint=partial_match_hint
        )
    
    def _prioritize_by_operations(
        self,
        buttons: List[ActionButton],
        operations: List[str]
    ) -> List[ActionButton]:
        """Reorder buttons to prioritize matching operations"""
        
        op_set = set(op.lower() for op in operations)
        
        # Separate matching and non-matching
        matching = []
        non_matching = []
        
        for button in buttons:
            if any(op.lower() in op_set for op in button.pipeline):
                matching.append(button)
            else:
                non_matching.append(button)
        
        return matching + non_matching
    
    def generate_multi_step_options(
        self,
        file_type: str,
        first_op: str
    ) -> DisambiguationResponse:
        """
        Generate options for multi-step pipelines.
        
        Args:
            file_type: Source file type
            first_op: First operation detected
        
        Returns:
            DisambiguationResponse for second step
        """
        
        common_second_steps = {
            "compress": ["convert", "split", "watermark"],
            "convert": ["compress", "ocr"],
            "ocr": ["compress", "split"],
            "merge": ["compress", "watermark", "page-numbers"],
            "split": ["compress", "convert"],
        }
        
        next_ops = common_second_steps.get(first_op.lower(), ["compress", "convert"])
        
        buttons = []
        for op in next_ops:
            # Find matching action button
            for action in self.pdf_actions + self.image_actions + self.docx_actions:
                if op.lower() in [p.lower() for p in action.pipeline]:
                    buttons.append(ActionButton(
                        id=f"{first_op}_{action.id}",
                        label=f"Then {action.label}",
                        description=action.description,
                        pipeline=[first_op, op],
                    ))
                    break
        
        # Add "just first op" option
        buttons.insert(0, ActionButton(
            id=f"just_{first_op}",
            label=f"Just {first_op.title()}",
            description=f"Only {first_op}, no additional steps",
            pipeline=[first_op],
            button_type=ButtonType.PRIMARY
        ))
        
        return DisambiguationResponse(
            message=f"Would you like to do anything after {first_op}?",
            buttons=buttons[:5],
            show_cancel=True
        )


# ============================================
# RESPONSE BUILDER
# ============================================

def build_disambiguation_ui(response: DisambiguationResponse) -> Dict[str, Any]:
    """
    Build a UI-ready response from DisambiguationResponse.
    
    Returns a dict suitable for JSON response.
    """
    
    return {
        "type": "disambiguation",
        "message": response.message,
        "buttons": [
            {
                "id": btn.id,
                "label": btn.label,
                "description": btn.description,
                "type": btn.button_type.value,
                "pipeline": btn.pipeline,
                "target_format": btn.target_format,
                "target_size_mb": btn.target_size_mb,
            }
            for btn in response.buttons
        ],
        "show_cancel": response.show_cancel,
        "context_hint": response.context_hint
    }


def handle_button_selection(
    button_id: str,
    response: DisambiguationResponse
) -> Optional[ActionButton]:
    """
    Handle user's button selection.
    
    Args:
        button_id: ID of selected button
        response: Original DisambiguationResponse
    
    Returns:
        Selected ActionButton or None if cancelled
    """
    
    if button_id == "cancel":
        return None
    
    for button in response.buttons:
        if button.id == button_id:
            return button
    
    return None


# Global generator instance
disambiguation_generator = DisambiguationGenerator()
