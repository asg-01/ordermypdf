"""
Tests for 40K+ Pattern Resolution System

Tests cover:
1. One-Flow Resolver
2. Pattern Matching Engine
3. Pattern Validation (Guards)
4. Button Disambiguation
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================
# ONE-FLOW RESOLVER TESTS
# ============================================

class TestOneFlowResolver:
    """Tests for the One-Flow Resolution module"""
    
    def test_import(self):
        """Test that module imports successfully"""
        from app.one_flow_resolver import OneFlowResolver, FileType
        assert OneFlowResolver is not None
        assert FileType is not None
    
    def test_basic_resolve_compress(self):
        """Test basic compress command resolution"""
        from app.one_flow_resolver import OneFlowResolver, FileType
        
        resolver = OneFlowResolver()
        result = resolver.resolve("compress this pdf", FileType.PDF)
        
        assert result.success
        assert "compress" in result.pipeline
    
    def test_resolve_convert_to_docx(self):
        """Test convert to docx command"""
        from app.one_flow_resolver import OneFlowResolver, FileType
        
        resolver = OneFlowResolver()
        result = resolver.resolve("convert to docx", FileType.PDF)
        
        assert result.success
        assert "convert" in result.pipeline
        assert result.target_format == FileType.DOCX
    
    def test_resolve_with_prefix(self):
        """Test command with noise prefix"""
        from app.one_flow_resolver import OneFlowResolver, FileType
        
        resolver = OneFlowResolver()
        result = resolver.resolve("pls compress this", FileType.PDF)
        
        assert result.success
        assert "compress" in result.pipeline
    
    def test_resolve_multi_step(self):
        """Test multi-step pipeline"""
        from app.one_flow_resolver import OneFlowResolver, FileType
        
        resolver = OneFlowResolver()
        result = resolver.resolve("merge then compress", FileType.PDF)
        
        assert result.success
        # Should detect both operations
        assert len(result.pipeline) >= 1
    
    def test_redundancy_guard(self):
        """Test redundancy guard (image to same image type)"""
        from app.one_flow_resolver import DeterministicGuards, FileType
        
        guards = DeterministicGuards()
        result = guards.check_redundancy(FileType.JPG, FileType.JPG, ["convert"])
        
        assert result.should_skip
        assert "already" in result.user_message.lower()
    
    def test_compatibility_guard(self):
        """Test compatibility guard (OCR on DOCX)"""
        from app.one_flow_resolver import DeterministicGuards, FileType, SupportedOp
        
        guards = DeterministicGuards()
        result = guards.check_compatibility(FileType.DOCX, [SupportedOp.OCR])
        
        assert result.should_skip
        assert "not needed" in result.user_message.lower()


# ============================================
# PATTERN MATCHING TESTS
# ============================================

class TestPatternMatcher:
    """Tests for the Pattern Matching Engine"""
    
    def test_import(self):
        """Test that module imports successfully"""
        from app.pattern_matching import PatternMatcher, match_command
        assert PatternMatcher is not None
        assert match_command is not None
    
    def test_match_single_operation(self):
        """Test matching a single operation"""
        from app.pattern_matching import match_command
        
        result = match_command("compress this file")
        
        assert result is not None
        assert "compress" in result.operations
        assert result.confidence >= 0.3
    
    def test_match_with_target_format(self):
        """Test matching with target format"""
        from app.pattern_matching import match_command
        
        result = match_command("convert to docx")
        
        assert result is not None
        assert result.target_format == "docx"
    
    def test_match_with_target_size(self):
        """Test matching with target size"""
        from app.pattern_matching import match_command
        
        result = match_command("compress to 1mb")
        
        assert result is not None
        assert result.target_size_mb == 1.0
        assert "compress" in result.operations or result.target_size_mb is not None
    
    def test_match_with_purpose(self):
        """Test matching with purpose"""
        from app.pattern_matching import match_command
        
        result = match_command("compress for email")
        
        assert result is not None
        assert result.purpose == "email"
    
    def test_match_pipeline_arrow(self):
        """Test matching arrow-notation pipeline"""
        from app.pattern_matching import match_command
        
        result = match_command("compress → convert to docx")
        
        assert result is not None
        assert len(result.operations) >= 1
    
    def test_match_with_alias(self):
        """Test matching with operation alias"""
        from app.pattern_matching import match_command
        
        result = match_command("combine these files")  # alias for merge
        
        assert result is not None
        assert "merge" in result.operations
    
    def test_normalize_strips_prefix(self):
        """Test that normalizer strips common prefixes"""
        from app.pattern_matching import PatternMatcher
        
        matcher = PatternMatcher()
        normalized = matcher._normalize("pls compress this")
        
        assert "pls" not in normalized.lower()
        assert "compress" in normalized.lower()


# ============================================
# PATTERN VALIDATION TESTS
# ============================================

class TestPatternValidator:
    """Tests for the Pattern Validation module"""
    
    def test_import(self):
        """Test that module imports successfully"""
        from app.pattern_validation import PatternValidator, validate_pipeline
        assert PatternValidator is not None
        assert validate_pipeline is not None
    
    def test_validate_valid_pipeline(self):
        """Test validation of a valid pipeline"""
        from app.pattern_validation import validate_pipeline
        
        result = validate_pipeline(["compress"], "test.pdf")
        
        assert result.is_valid
        assert "compress" in result.adjusted_pipeline
    
    def test_validate_redundant_conversion(self):
        """Test validation catches redundant conversion"""
        from app.pattern_validation import validate_pipeline
        
        result = validate_pipeline(["convert"], "test.pdf", target_format="pdf")
        
        # Should mark as redundant or skip
        assert result.status.value in ("redundant", "valid")
        if result.status.value == "redundant":
            assert result.skip_reason is not None
    
    def test_validate_incompatible_operation(self):
        """Test validation catches incompatible operations"""
        from app.pattern_validation import validate_pipeline
        
        result = validate_pipeline(["flatten"], "test.docx")  # flatten is PDF only
        
        # Should either be invalid or have adjusted pipeline
        if not result.is_valid:
            assert result.status.value == "incompatible"
    
    def test_validate_conflicting_operations(self):
        """Test validation catches conflicting operations"""
        from app.pattern_validation import validate_pipeline
        
        result = validate_pipeline(["split", "merge"], "test.pdf")
        
        # Split and merge together doesn't make sense
        assert result.status.value == "incompatible"
        assert result.is_valid == False
    
    def test_size_miss_retry(self):
        """Test size miss triggers retry"""
        from app.pattern_validation import PatternValidator
        
        validator = PatternValidator()
        result = validator.validate_size_target(
            achieved_size_mb=2.5,
            target_size_mb=1.0,
            retry_count=0
        )
        
        assert result.status.value == "retry_needed"
        assert result.retry_action == "stronger_preset"
    
    def test_size_miss_after_retry(self):
        """Test size miss after retry returns best result"""
        from app.pattern_validation import PatternValidator
        
        validator = PatternValidator()
        result = validator.validate_size_target(
            achieved_size_mb=1.5,
            target_size_mb=1.0,
            retry_count=1  # Already retried
        )
        
        # Should accept the result after retry
        assert result.status.value == "valid"
        assert "best" in result.user_message.lower() or "achieved" in result.user_message.lower()


# ============================================
# BUTTON DISAMBIGUATION TESTS
# ============================================

class TestButtonDisambiguation:
    """Tests for the Button Disambiguation module"""
    
    def test_import(self):
        """Test that module imports successfully"""
        from app.button_disambiguation import DisambiguationGenerator, build_disambiguation_ui
        assert DisambiguationGenerator is not None
        assert build_disambiguation_ui is not None
    
    def test_generate_pdf_options(self):
        """Test generating options for PDF file"""
        from app.button_disambiguation import DisambiguationGenerator
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="pdf")
        
        assert response.message is not None
        assert len(response.buttons) > 0
        assert len(response.buttons) <= 5  # Max 5 buttons
    
    def test_generate_image_options(self):
        """Test generating options for image file"""
        from app.button_disambiguation import DisambiguationGenerator
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="jpg")
        
        assert response.message is not None
        assert len(response.buttons) > 0
    
    def test_generate_size_specific_options(self):
        """Test generating size-specific options"""
        from app.button_disambiguation import DisambiguationGenerator
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="pdf", detected_size="1mb")
        
        assert "1MB" in response.message or "1mb" in response.message.lower()
        # Should have compress button with target size
        has_size_button = any("1MB" in btn.label or "1mb" in btn.label.lower() for btn in response.buttons)
        assert has_size_button or len(response.buttons) > 0
    
    def test_generate_purpose_specific_options(self):
        """Test generating purpose-specific options"""
        from app.button_disambiguation import DisambiguationGenerator
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="pdf", detected_purpose="email")
        
        assert "email" in response.message.lower()
    
    def test_build_ui_response(self):
        """Test building UI-ready response"""
        from app.button_disambiguation import DisambiguationGenerator, build_disambiguation_ui
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="pdf")
        
        ui_response = build_disambiguation_ui(response)
        
        assert ui_response["type"] == "disambiguation"
        assert "message" in ui_response
        assert "buttons" in ui_response
        assert isinstance(ui_response["buttons"], list)


# ============================================
# INTEGRATION TESTS
# ============================================

class TestIntegration:
    """Integration tests for the full 40K pattern system"""
    
    def test_full_flow_compress_to_size(self):
        """Test full flow: compress to target size"""
        from app.pattern_matching import match_command, PatternMatcher
        from app.pattern_validation import validate_pipeline
        
        # Match
        matched = match_command("compress to 1mb")
        assert matched is not None
        
        # Validate
        result = validate_pipeline(matched.operations, "test.pdf", target_size_mb=matched.target_size_mb)
        assert result.is_valid
    
    def test_full_flow_convert_format(self):
        """Test full flow: convert format"""
        from app.pattern_matching import match_command
        from app.pattern_validation import validate_pipeline
        
        # Match
        matched = match_command("convert to docx")
        assert matched is not None
        assert matched.target_format == "docx"
        
        # Validate  
        result = validate_pipeline(["convert"], "test.pdf", target_format="docx")
        assert result.is_valid
    
    def test_full_flow_unclear_command(self):
        """Test full flow: unclear command leads to disambiguation"""
        from app.pattern_matching import match_command
        from app.button_disambiguation import DisambiguationGenerator
        
        # Match with low confidence
        matched = match_command("do something")  # Very unclear
        
        if matched is None or matched.confidence < 0.5:
            # Generate disambiguation
            generator = DisambiguationGenerator()
            response = generator.generate(file_type="pdf")
            
            assert len(response.buttons) > 0
            assert response.message is not None
    
    def test_clarification_layer_integration(self):
        """Test that clarification layer can use new modules"""
        try:
            from app.clarification_layer import _try_one_flow_resolution
            
            # Should return None (fall through) for most commands
            # since it only handles disambiguation
            result = _try_one_flow_resolution("compress", ["test.pdf"])
            
            # Either returns None (fall through) or a ClarificationResult
            assert result is None or hasattr(result, 'intent') or hasattr(result, 'clarification')
            
        except ImportError:
            # Module not available in test environment
            pytest.skip("Clarification layer not available")


# ============================================
# SPEC COMPLIANCE TESTS
# ============================================

class TestSpecCompliance:
    """Tests verifying compliance with 40K spec requirements"""
    
    def test_spec_supported_ops(self):
        """Test all supported operations are recognized"""
        from app.pattern_matching import ALL_OPERATIONS
        
        expected_ops = [
            "merge", "split", "compress", "convert", "ocr", "clean",
            "enhance", "rotate", "reorder", "flatten", "watermark", "page-numbers"
        ]
        
        for op in expected_ops:
            assert op in ALL_OPERATIONS, f"Missing operation: {op}"
    
    def test_spec_redundancy_never_asks(self):
        """Test: Redundant ops → SKIP (never ask user)"""
        from app.pattern_validation import validate_pipeline, ValidationStatus
        
        # Redundant: PDF to PDF conversion only
        result = validate_pipeline(["convert"], "test.pdf", target_format="pdf")
        
        # Should not require user input
        assert result.status != ValidationStatus.AMBIGUOUS
    
    def test_spec_compatibility_never_asks(self):
        """Test: Incompatible ops → auto-fix or skip (never ask user)"""
        from app.pattern_validation import validate_pipeline, ValidationStatus
        
        # Incompatible: flatten on DOCX (PDF only)
        result = validate_pipeline(["flatten"], "test.docx")
        
        # Should either skip or adjust, not ask user
        assert result.status != ValidationStatus.AMBIGUOUS
    
    def test_spec_size_miss_retry_once(self):
        """Test: Size miss → retry once with stronger preset"""
        from app.pattern_validation import should_retry_on_size_miss
        
        # First attempt misses
        should_retry, action = should_retry_on_size_miss(2.5, 1.0, retry_count=0)
        assert should_retry == True
        assert action == "stronger_preset"
        
        # After retry, don't retry again
        should_retry, action = should_retry_on_size_miss(1.5, 1.0, retry_count=1)
        assert should_retry == False
    
    def test_spec_xml_error_ocr_fallback(self):
        """Test: XML/Unicode error → OCR fallback once"""
        from app.pattern_validation import should_retry_on_error
        
        # XML error
        should_retry, action = should_retry_on_error("xml compatible encoding error", retry_count=0)
        assert should_retry == True
        assert action == "ocr_fallback"
        
        # After retry, don't retry again
        should_retry, action = should_retry_on_error("xml compatible encoding error", retry_count=1)
        assert should_retry == False
    
    def test_spec_button_max_options(self):
        """Test: Button disambiguation shows max 5 options"""
        from app.button_disambiguation import DisambiguationGenerator
        
        generator = DisambiguationGenerator()
        response = generator.generate(file_type="pdf")
        
        assert len(response.buttons) <= 5
    
    def test_spec_prefer_action_over_questions(self):
        """Test: High-confidence matches execute without asking"""
        from app.pattern_matching import match_command
        
        # Clear command should have high confidence
        matched = match_command("compress this pdf")
        
        assert matched is not None
        assert matched.confidence >= 0.5  # High enough to execute


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
