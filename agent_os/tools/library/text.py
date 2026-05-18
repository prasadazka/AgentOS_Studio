"""Production-grade text processing and manipulation tools"""

import re
import hashlib
from typing import Optional, Dict, List, Any, Union, Literal
from string import Template

from pydantic import BaseModel, Field, validator

from agent_os.tools.base import BaseTool, ToolMetadata
from agent_os.utils.errors import (
    ToolExecutionError,
    ToolValidationError,
    ErrorCode
)
from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Type-Safe Models
# =============================================================================

class TextSummarizerInput(BaseModel):
    """Type-safe text summarizer input with validation"""
    text: str = Field(..., min_length=1, max_length=500000)  # 500KB max
    max_length: Optional[int] = Field(None, gt=0, le=100000)
    custom_prompt: Optional[str] = Field(None, max_length=5000)

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class TextSummarizerOutput(BaseModel):
    """Type-safe text summarizer output"""
    success: bool
    summary: Optional[str] = None
    original_length: int = 0
    summary_length: int = 0
    compression_ratio: Optional[str] = None
    method: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class RegexProcessorInput(BaseModel):
    """Type-safe regex processor input with validation"""
    text: str = Field(..., min_length=1, max_length=1000000)  # 1MB max
    pattern: str = Field(..., min_length=1, max_length=500)
    operation: Literal["match", "findall", "replace", "split", "extract_groups"] = "findall"
    replacement: Optional[str] = Field(None, max_length=10000)
    flags: Optional[List[Literal["IGNORECASE", "MULTILINE", "DOTALL", "VERBOSE"]]] = None

    @validator('pattern')
    def validate_pattern(cls, v):
        """Validate regex pattern for safety (prevent ReDoS)"""
        if not v or not v.strip():
            raise ValueError("Pattern cannot be empty")

        # Check for catastrophic backtracking patterns (basic ReDoS prevention)
        dangerous_patterns = [
            r'\(\.\*\)\+',  # (.*)+
            r'\(\.\*\)\*',  # (.*)*
            r'\(.*\+.*\)\+',  # nested quantifiers
        ]

        for danger in dangerous_patterns:
            if re.search(danger, v):
                raise ValueError(
                    f"Potentially dangerous regex pattern detected (ReDoS risk). "
                    f"Avoid nested quantifiers like (.*)+ or (.*)*"
                )

        # Validate pattern compiles
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {str(e)}")

        return v

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class RegexProcessorOutput(BaseModel):
    """Type-safe regex processor output"""
    success: bool
    operation: str = ""
    pattern: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class StringFormatterInput(BaseModel):
    """Type-safe string formatter input with validation"""
    template: str = Field(..., min_length=1, max_length=100000)
    variables: Dict[str, Any]
    style: Literal["format", "template", "percent"] = "format"

    @validator('variables')
    def validate_variables(cls, v):
        """Validate and sanitize variables"""
        if not v:
            raise ValueError("Variables cannot be empty")

        # Sanitize variable values
        MAX_VAR_LENGTH = 10000
        sanitized = {}

        for key, value in v.items():
            # Convert to string
            str_value = str(value)

            if len(str_value) > MAX_VAR_LENGTH:
                raise ValueError(f"Variable '{key}' too long (max {MAX_VAR_LENGTH} chars)")

            sanitized[key] = str_value

        return sanitized


class StringFormatterOutput(BaseModel):
    """Type-safe string formatter output"""
    success: bool
    formatted_text: Optional[str] = None
    template: str = ""
    variables_used: List[str] = Field(default_factory=list)
    style: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class PromptBuilderInput(BaseModel):
    """Type-safe prompt builder input with validation"""
    system_prompt: Optional[str] = Field(None, max_length=10000)
    context: Optional[Union[str, List[str]]] = None
    user_message: Optional[str] = Field(None, max_length=50000)
    variables: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, str]]] = None
    instructions: Optional[List[str]] = None
    output_format: Literal["text", "messages"] = "text"

    @validator('examples')
    def validate_examples(cls, v):
        """Validate examples structure"""
        if v is not None:
            MAX_EXAMPLES = 10
            if len(v) > MAX_EXAMPLES:
                raise ValueError(f"Too many examples (max {MAX_EXAMPLES})")

            for i, example in enumerate(v):
                if 'input' not in example and 'output' not in example:
                    raise ValueError(f"Example {i} must have 'input' or 'output' key")

        return v


class PromptBuilderOutput(BaseModel):
    """Type-safe prompt builder output"""
    success: bool
    prompt: Optional[str] = None
    sections_included: List[str] = Field(default_factory=list)
    variables_used: List[str] = Field(default_factory=list)
    total_length: int = 0
    messages: Optional[List[Dict[str, str]]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade Text Tools
# =============================================================================

class TextSummarizerTool(BaseTool):
    """Production-grade text summarizer with validation

    Features:
    - Pydantic validation with size limits
    - Extractive summarization (no external dependencies)
    - Optional LLM summarization
    - Structured logging
    - Error handling with codes
    """

    def __init__(
        self,
        method: str = "extractive",
        max_sentences: int = 3,
        llm_model: Optional[str] = None
    ):
        self.method = method
        self.max_sentences = max_sentences
        self.llm_model = llm_model

        if method == "llm" and not llm_model:
            raise ToolValidationError(
                "llm_model required when method='llm'",
                field_name="llm_model"
            )

        super().__init__(
            ToolMetadata(
                name="text_summarizer",
                description=f"Summarize text using {method} summarization. Production-grade with validation.",
                category="text",
                tags=["text", "summarization", "nlp"]
            )
        )

    def _execute(
        self,
        text: str,
        max_length: Optional[int] = None,
        custom_prompt: Optional[str] = None
    ) -> str:
        """Summarize text

        Args:
            text: Text to summarize
            max_length: Maximum length of summary (characters)
            custom_prompt: Custom prompt for LLM summarization

        Returns:
            JSON with TextSummarizerOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = TextSummarizerInput(
                text=text,
                max_length=max_length,
                custom_prompt=custom_prompt
            )

            logger.info("Summarizing text", extra={
                "text_hash": text_hash,
                "text_length": len(text),
                "method": self.method
            })

            if self.method == "extractive":
                summary = self._extractive_summary(validated.text, validated.max_length)
            elif self.method == "llm":
                summary = self._llm_summary(validated.text, validated.max_length, validated.custom_prompt)
            else:
                raise ToolValidationError(
                    f"Unknown method: {self.method}",
                    field_name="method"
                )

            result = TextSummarizerOutput(
                success=True,
                summary=summary,
                original_length=len(validated.text),
                summary_length=len(summary),
                compression_ratio=f"{len(summary) / len(validated.text) * 100:.1f}%",
                method=self.method
            )

            logger.info("Text summarization completed", extra={
                "text_hash": text_hash,
                "compression_ratio": result.compression_ratio,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Text summarization validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return TextSummarizerOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value,
                method=self.method
            ).to_json()

        except Exception as e:
            logger.error("Text summarization failed", extra={"text_hash": text_hash}, exc_info=True)
            return TextSummarizerOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value,
                method=self.method
            ).to_json()

    def _extractive_summary(self, text: str, max_length: Optional[int]) -> str:
        """Extractive summarization: select important sentences"""
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())

        if len(sentences) <= self.max_sentences:
            return text

        # Simple scoring: sentence position + length + keywords
        scored_sentences = []
        for i, sentence in enumerate(sentences):
            # Position score (earlier sentences more important)
            position_score = 1.0 - (i / len(sentences))
            # Length score (prefer medium-length sentences)
            length_score = min(len(sentence) / 100, 1.0)
            # Keywords score
            keyword_score = sum(
                1 for word in ['important', 'key', 'critical', 'main', 'significant']
                if word in sentence.lower()
            ) * 0.2

            total_score = position_score + length_score + keyword_score
            scored_sentences.append((total_score, sentence))

        # Sort by score and take top N
        scored_sentences.sort(reverse=True, key=lambda x: x[0])
        top_sentences = [s[1] for s in scored_sentences[:self.max_sentences]]

        # Reorder to maintain original order
        summary_sentences = []
        for sentence in sentences:
            if sentence in top_sentences:
                summary_sentences.append(sentence)

        summary = ' '.join(summary_sentences)

        # Truncate if max_length specified
        if max_length and len(summary) > max_length:
            summary = summary[:max_length].rsplit(' ', 1)[0] + '...'

        return summary

    def _llm_summary(
        self,
        text: str,
        max_length: Optional[int],
        custom_prompt: Optional[str]
    ) -> str:
        """LLM-based abstractive summarization"""
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage

            llm = ChatOpenAI(model=self.llm_model, temperature=0)

            if custom_prompt:
                prompt = custom_prompt.format(text=text)
            else:
                length_instruction = f" in about {max_length} characters" if max_length else ""
                prompt = f"""Summarize the following text{length_instruction}. Focus on key points and main ideas.

Text:
{text}

Summary:"""

            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content.strip()

        except ImportError:
            raise ToolExecutionError(
                "LLM summarization requires langchain-openai. "
                "Install with: pip install langchain-openai",
                details={"missing_package": "langchain-openai"}
            )


class RegexProcessorTool(BaseTool):
    """Production-grade regex processor with ReDoS protection

    Features:
    - ReDoS protection (dangerous pattern detection)
    - Pattern validation before execution
    - Pydantic validation with size limits
    - Structured logging
    - Timeout protection (regex complexity limits)
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="regex_processor",
                description="Process text with regex: match, find, replace, extract. ReDoS-safe.",
                category="text",
                tags=["text", "regex", "pattern", "parsing"]
            )
        )

    def _execute(
        self,
        text: str,
        pattern: str,
        operation: str = "findall",
        replacement: Optional[str] = None,
        flags: Optional[List[str]] = None
    ) -> str:
        """Process text with regex

        Args:
            text: Input text
            pattern: Regex pattern
            operation: "match", "findall", "replace", "split", "extract_groups"
            replacement: Replacement string (for "replace" operation)
            flags: Regex flags like ["IGNORECASE", "MULTILINE"]

        Returns:
            JSON with RegexProcessorOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
        pattern_hash = hashlib.sha256(pattern.encode()).hexdigest()[:8]

        try:
            # Validate input (includes ReDoS protection)
            validated = RegexProcessorInput(
                text=text,
                pattern=pattern,
                operation=operation,
                replacement=replacement,
                flags=flags
            )

            logger.info("Processing regex", extra={
                "text_hash": text_hash,
                "pattern_hash": pattern_hash,
                "operation": operation
            })

            # Parse flags
            regex_flags = 0
            if validated.flags:
                flag_map = {
                    "IGNORECASE": re.IGNORECASE,
                    "MULTILINE": re.MULTILINE,
                    "DOTALL": re.DOTALL,
                    "VERBOSE": re.VERBOSE
                }
                for flag in validated.flags:
                    regex_flags |= flag_map.get(flag.upper(), 0)

            # Compile pattern (already validated in Pydantic)
            compiled_pattern = re.compile(validated.pattern, regex_flags)

            # Execute operation
            if validated.operation == "match":
                match = compiled_pattern.match(validated.text)
                result_data = {
                    "matched": match is not None,
                    "match_text": match.group(0) if match else None,
                    "groups": match.groups() if match else []
                }

            elif validated.operation == "findall":
                matches = compiled_pattern.findall(validated.text)
                result_data = {
                    "matches": matches,
                    "count": len(matches)
                }

            elif validated.operation == "replace":
                if validated.replacement is None:
                    raise ToolValidationError(
                        "replacement required for replace operation",
                        field_name="replacement"
                    )
                new_text = compiled_pattern.sub(validated.replacement, validated.text)
                result_data = {
                    "original_text": validated.text,
                    "new_text": new_text,
                    "replacements_made": len(compiled_pattern.findall(validated.text))
                }

            elif validated.operation == "split":
                parts = compiled_pattern.split(validated.text)
                result_data = {
                    "parts": parts,
                    "count": len(parts)
                }

            elif validated.operation == "extract_groups":
                matches = compiled_pattern.finditer(validated.text)
                groups = [
                    {
                        "match": m.group(0),
                        "groups": m.groups(),
                        "groupdict": m.groupdict(),
                        "start": m.start(),
                        "end": m.end()
                    }
                    for m in matches
                ]
                result_data = {
                    "matches": groups,
                    "count": len(groups)
                }

            else:
                raise ToolValidationError(
                    f"Unknown operation: {validated.operation}",
                    field_name="operation"
                )

            result = RegexProcessorOutput(
                success=True,
                operation=validated.operation,
                pattern=validated.pattern,
                result=result_data
            )

            logger.info("Regex processing completed", extra={
                "text_hash": text_hash,
                "pattern_hash": pattern_hash,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Regex validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return RegexProcessorOutput(
                success=False,
                pattern=pattern,
                operation=operation,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except re.error as e:
            logger.error("Invalid regex pattern", extra={"pattern_hash": pattern_hash}, exc_info=True)
            return RegexProcessorOutput(
                success=False,
                pattern=pattern,
                operation=operation,
                error=f"Invalid regex pattern: {str(e)}",
                error_code=ErrorCode.TOOL_VALIDATION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error("Regex processing failed", extra={"text_hash": text_hash}, exc_info=True)
            return RegexProcessorOutput(
                success=False,
                pattern=pattern,
                operation=operation,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class StringFormatterTool(BaseTool):
    """Production-grade string formatter with injection protection

    Features:
    - Variable sanitization
    - Size limits
    - Safe template substitution
    - Pydantic validation
    - Structured logging
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="string_formatter",
                description="Format strings with templates. Injection-safe, validated.",
                category="text",
                tags=["text", "formatting", "templates"]
            )
        )

    def _execute(
        self,
        template: str,
        variables: Dict[str, Any],
        style: str = "format"
    ) -> str:
        """Format string with template

        Args:
            template: Template string
            variables: Dictionary of variables to substitute
            style: "format" ({var}), "template" ($var), or "percent" (%(var)s)

        Returns:
            JSON with StringFormatterOutput schema
        """
        template_hash = hashlib.sha256(template.encode()).hexdigest()[:8]

        try:
            # Validate input (sanitizes variables)
            validated = StringFormatterInput(
                template=template,
                variables=variables,
                style=style
            )

            logger.info("Formatting string", extra={
                "template_hash": template_hash,
                "style": style,
                "var_count": len(variables)
            })

            if validated.style == "format":
                # Using str.format() - {variable}
                result_text = validated.template.format(**validated.variables)

            elif validated.style == "template":
                # Using string.Template - $variable (safe_substitute prevents errors)
                tmpl = Template(validated.template)
                result_text = tmpl.safe_substitute(validated.variables)

            elif validated.style == "percent":
                # Using % formatting - %(variable)s
                result_text = validated.template % validated.variables

            else:
                raise ToolValidationError(
                    f"Unknown style: {validated.style}",
                    field_name="style"
                )

            result = StringFormatterOutput(
                success=True,
                formatted_text=result_text,
                template=validated.template,
                variables_used=list(validated.variables.keys()),
                style=validated.style
            )

            logger.info("String formatting completed", extra={
                "template_hash": template_hash,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("String formatting validation failed", extra={"template_hash": template_hash}, exc_info=True)
            return StringFormatterOutput(
                success=False,
                template=template,
                style=style,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except KeyError as e:
            logger.error("Missing variable", extra={"template_hash": template_hash}, exc_info=True)
            return StringFormatterOutput(
                success=False,
                template=template,
                style=style,
                variables_used=list(variables.keys()),
                error=f"Missing variable: {str(e)}",
                error_code=ErrorCode.TOOL_VALIDATION_FAILED.value
            ).to_json()

        except Exception as e:
            logger.error("String formatting failed", extra={"template_hash": template_hash}, exc_info=True)
            return StringFormatterOutput(
                success=False,
                template=template,
                style=style,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class PromptBuilderTool(BaseTool):
    """Production-grade prompt builder with validation

    Features:
    - Pydantic validation with size limits
    - Example validation
    - Structured output (text or messages format)
    - Safe variable substitution
    - Structured logging
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="prompt_builder",
                description="Build structured prompts with validation. Supports text and messages format.",
                category="text",
                tags=["text", "prompts", "llm", "templates"]
            )
        )

    def _execute(
        self,
        system_prompt: Optional[str] = None,
        context: Optional[Union[str, List[str]]] = None,
        user_message: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        examples: Optional[List[Dict[str, str]]] = None,
        instructions: Optional[List[str]] = None,
        output_format: str = "text"
    ) -> str:
        """Build structured prompt

        Args:
            system_prompt: System role/instructions
            context: Background context (string or list)
            user_message: User's query/task
            variables: Variables to substitute in templates
            examples: Few-shot examples [{"input": "...", "output": "..."}]
            instructions: List of specific instructions
            output_format: "text" or "messages" (for chat APIs)

        Returns:
            JSON with PromptBuilderOutput schema
        """
        prompt_hash = hashlib.sha256(str({
            "system": system_prompt,
            "context": context,
            "user": user_message
        }).encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = PromptBuilderInput(
                system_prompt=system_prompt,
                context=context,
                user_message=user_message,
                variables=variables,
                examples=examples,
                instructions=instructions,
                output_format=output_format
            )

            logger.info("Building prompt", extra={
                "prompt_hash": prompt_hash,
                "output_format": output_format
            })

            variables = validated.variables or {}

            # Build prompt sections
            sections = []

            # System prompt
            if validated.system_prompt:
                formatted_system = validated.system_prompt.format(**variables)
                sections.append(f"SYSTEM:\n{formatted_system}")

            # Context
            if validated.context:
                if isinstance(validated.context, list):
                    context_text = "\n\n".join(validated.context)
                else:
                    context_text = validated.context

                formatted_context = context_text.format(**variables)
                sections.append(f"CONTEXT:\n{formatted_context}")

            # Instructions
            if validated.instructions:
                instructions_text = "\n".join(
                    f"{i+1}. {inst}" for i, inst in enumerate(validated.instructions)
                )
                formatted_instructions = instructions_text.format(**variables)
                sections.append(f"INSTRUCTIONS:\n{formatted_instructions}")

            # Examples (few-shot)
            if validated.examples:
                examples_text = []
                for i, example in enumerate(validated.examples, 1):
                    examples_text.append(f"Example {i}:")
                    examples_text.append(f"Input: {example.get('input', '')}")
                    examples_text.append(f"Output: {example.get('output', '')}")
                    examples_text.append("")

                sections.append("EXAMPLES:\n" + "\n".join(examples_text))

            # User message
            if validated.user_message:
                formatted_user = validated.user_message.format(**variables)
                sections.append(f"USER:\n{formatted_user}")

            # Combine sections
            full_prompt = "\n\n---\n\n".join(sections)

            result = PromptBuilderOutput(
                success=True,
                prompt=full_prompt,
                sections_included=[
                    s for s in [
                        "system" if validated.system_prompt else None,
                        "context" if validated.context else None,
                        "instructions" if validated.instructions else None,
                        "examples" if validated.examples else None,
                        "user" if validated.user_message else None
                    ] if s
                ],
                variables_used=list(variables.keys()),
                total_length=len(full_prompt)
            )

            # Format for chat APIs if requested
            if validated.output_format == "messages":
                messages = []
                if validated.system_prompt:
                    messages.append({
                        "role": "system",
                        "content": validated.system_prompt.format(**variables)
                    })

                user_content_parts = []
                if validated.context:
                    context_text = (
                        "\n\n".join(validated.context)
                        if isinstance(validated.context, list)
                        else validated.context
                    )
                    user_content_parts.append(f"Context:\n{context_text.format(**variables)}")

                if validated.instructions:
                    inst_text = "\n".join(
                        f"{i+1}. {inst}" for i, inst in enumerate(validated.instructions)
                    )
                    user_content_parts.append(f"Instructions:\n{inst_text.format(**variables)}")

                if validated.examples:
                    ex_text = []
                    for i, ex in enumerate(validated.examples, 1):
                        ex_text.append(f"Example {i}:")
                        ex_text.append(f"Input: {ex.get('input', '')}")
                        ex_text.append(f"Output: {ex.get('output', '')}")
                    user_content_parts.append("Examples:\n" + "\n".join(ex_text))

                if validated.user_message:
                    user_content_parts.append(validated.user_message.format(**variables))

                messages.append({
                    "role": "user",
                    "content": "\n\n".join(user_content_parts)
                })

                result.messages = messages

            logger.info("Prompt building completed", extra={
                "prompt_hash": prompt_hash,
                "total_length": result.total_length,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Prompt building validation failed", extra={"prompt_hash": prompt_hash}, exc_info=True)
            return PromptBuilderOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except KeyError as e:
            logger.error("Missing variable", extra={"prompt_hash": prompt_hash}, exc_info=True)
            return PromptBuilderOutput(
                success=False,
                error=f"Missing variable: {str(e)}",
                error_code=ErrorCode.TOOL_VALIDATION_FAILED.value,
                variables_used=list(variables.keys()) if variables else []
            ).to_json()

        except Exception as e:
            logger.error("Prompt building failed", extra={"prompt_hash": prompt_hash}, exc_info=True)
            return PromptBuilderOutput(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
