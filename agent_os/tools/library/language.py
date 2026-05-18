"""Production-grade language detection and translation tools"""

import hashlib
from typing import Optional, List, Dict, Any, Literal

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

class LanguageDetectInput(BaseModel):
    """Type-safe language detection input with validation"""
    text: str = Field(..., min_length=1, max_length=100000)  # 100KB max
    detailed: bool = False

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class LanguageDetectOutput(BaseModel):
    """Type-safe language detection output"""
    success: bool
    language: Optional[str] = None
    primary_language: Optional[str] = None
    confidence: Optional[float] = None
    all_languages: List[Dict[str, Any]] = Field(default_factory=list)
    text_length: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class TranslationInput(BaseModel):
    """Type-safe translation input with validation"""
    text: str = Field(..., min_length=1, max_length=100000)  # 100KB max
    target_language: str = Field(..., min_length=2, max_length=5)
    source_language: str = Field("auto", min_length=2, max_length=5)

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v

    @validator('target_language', 'source_language')
    def validate_language_code(cls, v):
        """Validate language code format"""
        if v == "auto":
            return v

        # ISO 639-1 (2-letter) or ISO 639-3 (3-letter) codes
        if not v.isalpha() or len(v) not in [2, 3, 5]:  # 5 for locale like en-US
            raise ValueError(f"Invalid language code format: {v}")

        return v.lower()


class TranslationOutput(BaseModel):
    """Type-safe translation output"""
    success: bool
    translated_text: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    original_text: Optional[str] = None
    backend: str = ""
    model: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


class MultilingualInput(BaseModel):
    """Type-safe multilingual processing input"""
    text: str = Field(..., min_length=1, max_length=100000)
    target_language: Optional[str] = Field(None, min_length=2, max_length=5)
    translate_if_needed: bool = True

    @validator('text')
    def validate_text(cls, v):
        """Validate text content"""
        if not v or not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class MultilingualOutput(BaseModel):
    """Type-safe multilingual processing output"""
    success: bool
    detected_language: Optional[str] = None
    original_text: Optional[str] = None
    text_length: int = 0
    translation_needed: bool = False
    translated_text: Optional[str] = None
    target_language: Optional[str] = None
    message: Optional[str] = None
    translation_error: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)


# =============================================================================
# Production-Grade Language Tools
# =============================================================================

class LanguageDetectorTool(BaseTool):
    """Production-grade language detector with validation

    Features:
    - Pydantic validation with size limits
    - Structured logging
    - Error handling with codes
    - Support for multiple language probabilities
    """

    def __init__(self):
        super().__init__(
            ToolMetadata(
                name="language_detector",
                description="Detect language with production-grade validation. Returns ISO 639-1 code.",
                category="language",
                tags=["language", "detection", "i18n", "nlp"]
            )
        )

    def _execute(self, text: str, detailed: bool = False) -> str:
        """Detect language of text

        Args:
            text: Text to analyze
            detailed: If True, return probabilities for multiple languages

        Returns:
            JSON with LanguageDetectOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = LanguageDetectInput(
                text=text,
                detailed=detailed
            )

            logger.info("Detecting language", extra={
                "text_hash": text_hash,
                "text_length": len(text),
                "detailed": detailed
            })

            from langdetect import detect, detect_langs, LangDetectException

            try:
                if validated.detailed:
                    # Get probabilities for multiple languages
                    results = detect_langs(validated.text)
                    languages = [
                        {
                            "language": str(lang.lang),
                            "probability": float(lang.prob)
                        }
                        for lang in results
                    ]

                    result = LanguageDetectOutput(
                        success=True,
                        primary_language=str(results[0].lang),
                        confidence=float(results[0].prob),
                        all_languages=languages,
                        text_length=len(validated.text)
                    )
                else:
                    # Simple detection
                    language = detect(validated.text)
                    result = LanguageDetectOutput(
                        success=True,
                        language=language,
                        text_length=len(validated.text)
                    )

                logger.info("Language detection completed", extra={
                    "text_hash": text_hash,
                    "detected_language": result.language or result.primary_language,
                    "status": "success"
                })

                return result.to_json()

            except LangDetectException as e:
                logger.error("Language detection failed", extra={"text_hash": text_hash}, exc_info=True)
                return LanguageDetectOutput(
                    success=False,
                    text_length=len(validated.text),
                    error=f"Language detection failed: {str(e)}",
                    error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
                ).to_json()

        except ImportError:
            logger.error("langdetect not installed", extra={"text_hash": text_hash})
            return LanguageDetectOutput(
                success=False,
                error="langdetect not installed. Install with: pip install langdetect",
                error_code=ErrorCode.TOOL_DEPENDENCY_MISSING.value
            ).to_json()

        except ToolValidationError as e:
            logger.error("Language detection validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return LanguageDetectOutput(
                success=False,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Language detection failed", extra={"text_hash": text_hash}, exc_info=True)
            return LanguageDetectOutput(
                success=False,
                text_length=len(text),
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()


class TranslationTool(BaseTool):
    """Production-grade translation tool with multiple backends

    Features:
    - Pydantic validation with language code validation
    - Multiple backends (googletrans, google_cloud, deepl, llm)
    - Structured logging
    - Error handling with codes
    - Size limits

    Supported backends:
    - googletrans: Free, unofficial Google Translate API
    - google_cloud: Official Google Cloud Translation API (API key required)
    - deepl: DeepL API (API key required, high quality)
    - llm: Use LLM for translation (flexible, requires LLM API key)
    """

    def __init__(
        self,
        backend: Literal["googletrans", "google_cloud", "deepl", "llm"] = "googletrans",
        api_key: Optional[str] = None,
        llm_model: Optional[str] = None
    ):
        self.backend = backend
        self.api_key = api_key
        self.llm_model = llm_model

        if backend in ["google_cloud", "deepl"] and not api_key:
            raise ToolValidationError(
                f"{backend} requires api_key parameter",
                field_name="api_key"
            )

        if backend == "llm" and not llm_model:
            raise ToolValidationError(
                "llm backend requires llm_model parameter",
                field_name="llm_model"
            )

        super().__init__(
            ToolMetadata(
                name="translator",
                description=f"Translate text using {backend}. Production-grade with validation.",
                category="language",
                tags=["language", "translation", "i18n", backend]
            )
        )

    def _execute(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto"
    ) -> str:
        """Translate text

        Args:
            text: Text to translate
            target_language: Target language code (e.g., "en", "es", "fr")
            source_language: Source language code or "auto" for auto-detection

        Returns:
            JSON with TranslationOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = TranslationInput(
                text=text,
                target_language=target_language,
                source_language=source_language
            )

            logger.info("Translating text", extra={
                "text_hash": text_hash,
                "text_length": len(text),
                "target_language": target_language,
                "backend": self.backend
            })

            if self.backend == "googletrans":
                result = self._translate_googletrans(validated)
            elif self.backend == "google_cloud":
                result = self._translate_google_cloud(validated)
            elif self.backend == "deepl":
                result = self._translate_deepl(validated)
            elif self.backend == "llm":
                result = self._translate_llm(validated)
            else:
                raise ToolValidationError(
                    f"Unknown backend: {self.backend}",
                    field_name="backend"
                )

            logger.info("Translation completed", extra={
                "text_hash": text_hash,
                "backend": self.backend,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Translation validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return TranslationOutput(
                success=False,
                backend=self.backend,
                target_language=target_language,
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Translation failed", extra={"text_hash": text_hash}, exc_info=True)
            return TranslationOutput(
                success=False,
                backend=self.backend,
                target_language=target_language,
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()

    def _translate_googletrans(self, validated: TranslationInput) -> TranslationOutput:
        """Translate using googletrans (free, unofficial)"""
        try:
            from googletrans import Translator

            translator = Translator()
            result = translator.translate(
                validated.text,
                dest=validated.target_language,
                src=validated.source_language if validated.source_language != "auto" else "auto"
            )

            return TranslationOutput(
                success=True,
                translated_text=result.text,
                source_language=result.src,
                target_language=result.dest,
                original_text=validated.text,
                backend="googletrans"
            )

        except ImportError:
            raise ToolExecutionError(
                "googletrans not installed. Install with: pip install googletrans==4.0.0-rc1",
                details={"missing_package": "googletrans"}
            )

    def _translate_google_cloud(self, validated: TranslationInput) -> TranslationOutput:
        """Translate using Google Cloud Translation API"""
        try:
            from google.cloud import translate_v2 as translate

            client = translate.Client(credentials=self.api_key)

            result = client.translate(
                validated.text,
                target_language=validated.target_language,
                source_language=validated.source_language if validated.source_language != "auto" else None
            )

            return TranslationOutput(
                success=True,
                translated_text=result["translatedText"],
                source_language=result.get("detectedSourceLanguage", validated.source_language),
                target_language=validated.target_language,
                original_text=validated.text,
                backend="google_cloud"
            )

        except ImportError:
            raise ToolExecutionError(
                "google-cloud-translate not installed. "
                "Install with: pip install google-cloud-translate",
                details={"missing_package": "google-cloud-translate"}
            )

    def _translate_deepl(self, validated: TranslationInput) -> TranslationOutput:
        """Translate using DeepL API"""
        try:
            import deepl

            translator = deepl.Translator(self.api_key)

            result = translator.translate_text(
                validated.text,
                target_lang=validated.target_language.upper(),
                source_lang=validated.source_language.upper() if validated.source_language != "auto" else None
            )

            return TranslationOutput(
                success=True,
                translated_text=result.text,
                source_language=result.detected_source_lang.lower(),
                target_language=validated.target_language.lower(),
                original_text=validated.text,
                backend="deepl"
            )

        except ImportError:
            raise ToolExecutionError(
                "deepl not installed. Install with: pip install deepl",
                details={"missing_package": "deepl"}
            )

    def _translate_llm(self, validated: TranslationInput) -> TranslationOutput:
        """Translate using LLM"""
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage

            llm = ChatOpenAI(model=self.llm_model, temperature=0)

            # Build translation prompt
            if validated.source_language == "auto":
                prompt = f"""Translate the following text to {validated.target_language}.

Text:
{validated.text}

Translation:"""
            else:
                prompt = f"""Translate the following text from {validated.source_language} to {validated.target_language}.

Text:
{validated.text}

Translation:"""

            response = llm.invoke([HumanMessage(content=prompt)])
            translated = response.content.strip()

            return TranslationOutput(
                success=True,
                translated_text=translated,
                source_language=validated.source_language,
                target_language=validated.target_language,
                original_text=validated.text,
                backend="llm",
                model=self.llm_model
            )

        except ImportError:
            raise ToolExecutionError(
                "LLM translation requires langchain-openai. "
                "Install with: pip install langchain-openai",
                details={"missing_package": "langchain-openai"}
            )


class MultilingualTextTool(BaseTool):
    """Production-grade combined language detection and translation

    Features:
    - Automatic language detection
    - Conditional translation (only if needed)
    - Pydantic validation
    - Structured logging
    - Reuses validated detector and translator
    """

    def __init__(
        self,
        translation_backend: Literal["googletrans", "google_cloud", "deepl", "llm"] = "googletrans",
        api_key: Optional[str] = None,
        llm_model: Optional[str] = None
    ):
        self.detector = LanguageDetectorTool()
        self.translator = TranslationTool(
            backend=translation_backend,
            api_key=api_key,
            llm_model=llm_model
        )

        super().__init__(
            ToolMetadata(
                name="multilingual_processor",
                description="Detect language and optionally translate. Production-grade, validated.",
                category="language",
                tags=["language", "translation", "detection", "i18n"]
            )
        )

    def _execute(
        self,
        text: str,
        target_language: Optional[str] = None,
        translate_if_needed: bool = True
    ) -> str:
        """Process multilingual text

        Args:
            text: Input text
            target_language: Desired output language (e.g., "en")
            translate_if_needed: If True, translate if source != target

        Returns:
            JSON with MultilingualOutput schema
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]

        try:
            # Validate input
            validated = MultilingualInput(
                text=text,
                target_language=target_language,
                translate_if_needed=translate_if_needed
            )

            logger.info("Processing multilingual text", extra={
                "text_hash": text_hash,
                "target_language": target_language
            })

            # Step 1: Detect language
            detection_result_json = self.detector._execute(validated.text)
            detection_result = LanguageDetectOutput.model_validate_json(detection_result_json)

            if not detection_result.success:
                return MultilingualOutput(
                    success=False,
                    error=detection_result.error,
                    error_code=detection_result.error_code
                ).to_json()

            source_lang = detection_result.language

            result = MultilingualOutput(
                success=True,
                detected_language=source_lang,
                original_text=validated.text,
                text_length=len(validated.text)
            )

            # Step 2: Translate if needed
            if validated.target_language and validated.translate_if_needed:
                if source_lang == validated.target_language:
                    result.translation_needed = False
                    result.translated_text = validated.text
                    result.message = f"Text is already in {validated.target_language}"
                else:
                    result.translation_needed = True
                    translation_result_json = self.translator._execute(
                        validated.text,
                        validated.target_language,
                        source_lang
                    )
                    translation_result = TranslationOutput.model_validate_json(translation_result_json)

                    if not translation_result.success:
                        result.translation_error = translation_result.error
                    else:
                        result.translated_text = translation_result.translated_text
                        result.target_language = validated.target_language
            else:
                result.translation_needed = False

            logger.info("Multilingual processing completed", extra={
                "text_hash": text_hash,
                "detected_language": source_lang,
                "translation_needed": result.translation_needed,
                "status": "success"
            })

            return result.to_json()

        except ToolValidationError as e:
            logger.error("Multilingual validation failed", extra={"text_hash": text_hash}, exc_info=True)
            return MultilingualOutput(
                success=False,
                text_length=len(text),
                error=str(e),
                error_code=e.error_code.value
            ).to_json()

        except Exception as e:
            logger.error("Multilingual processing failed", extra={"text_hash": text_hash}, exc_info=True)
            return MultilingualOutput(
                success=False,
                text_length=len(text),
                error=f"{type(e).__name__}: {str(e)}",
                error_code=ErrorCode.TOOL_EXECUTION_FAILED.value
            ).to_json()
