"""
Quality Gate Component

Evaluates article quality using LLM judge.
Regenerates articles that fail, with feedback for improvement.
"""

import logging
from typing import Dict, List, Optional, Tuple, Union, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from scripts import prompts
from scripts.config import AppConfig
from scripts.models import AdaptedArticle, QualityResult, SourceArticle, Topic


class JudgeResponse(BaseModel):
    grammar_score: float = Field(..., description="Score for grammar and language use")
    grammar_issues: List[str] = Field(default_factory=list, description="Grammar issues found")
    educational_score: float = Field(..., description="Score for educational value")
    educational_notes: Optional[str] = Field(
        default=None, description="Notes about educational aspects"
    )
    content_score: float = Field(..., description="Score for content quality")
    content_issues: List[str] = Field(default_factory=list, description="Content issues")
    level_score: float = Field(..., description="Score for level appropriateness")
    total_score: float = Field(..., description="Total aggregated score")
    issues: List[str] = Field(default_factory=list, description="Actionable issues to fix")
    strengths: List[str] = Field(default_factory=list, description="Strengths identified")
    recommendation: Optional[str] = Field(default=None, description="PASS/FAIL recommendation")


class QualityGate:
    """Quality checking with smart regeneration"""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('QualityGate')

        self.quality_config = config.quality_gate.model_dump()
        self.min_score = self.quality_config['min_score']
        self.max_attempts = self.quality_config['max_attempts']
        self.llm_config = config.llm.model_dump()
        self.quality_temperature = self.llm_config.get(
            'quality_temperature', self.llm_config.get('temperature', 0.1)
        )

        # Initialize LLM client
        self._init_llm_client()
        self._init_judge_chain()

    def _init_llm_client(self):
        """Initialize LLM client (Anthropic or OpenAI) based on config"""
        provider = self.llm_config['provider']

        if provider == 'anthropic':
            api_key = self.llm_config.get('anthropic_api_key')
            if not api_key:
                raise ValueError("Missing ANTHROPIC_API_KEY in config/environment")

            self.llm_client: Union[ChatAnthropic, ChatOpenAI] = ChatAnthropic(
                api_key=api_key,
                model=self.llm_config['models']['quality_check'],
                max_tokens=self.llm_config.get('max_tokens', 4096),
                temperature=self.quality_temperature,
            )
            self.logger.info("Initialized Anthropic client for quality checks")

        elif provider == 'openai':
            api_key = self.llm_config.get('openai_api_key')
            if not api_key:
                raise ValueError("Missing OPENAI_API_KEY in config/environment")

            self.llm_client = ChatOpenAI(
                api_key=api_key,
                model=self.llm_config['models']['quality_check'],
                max_tokens=self.llm_config.get('max_tokens', 4096),
                temperature=self.quality_temperature,
                model_kwargs={'response_format': {'type': 'json_object'}},
            )
            self.logger.info("Initialized OpenAI client for quality checks")

        else:
            raise ValueError(f"Unknown LLM provider: {provider}")

    def _init_judge_chain(self):
        """Build a LangChain pipeline that enforces structured JSON responses."""
        parser = PydanticOutputParser(pydantic_object=JudgeResponse)
        self.format_instructions = parser.get_format_instructions()

        structured_llm = cast(
            ChatAnthropic | ChatOpenAI, self.llm_client
        ).with_structured_output(JudgeResponse)

        self.judge_prompt = ChatPromptTemplate.from_messages([
            ("user", "{prompt}\n\n{format_instructions}"),
        ])

        self.judge_chain = self.judge_prompt | structured_llm

    def check_and_improve(
        self,
        article: AdaptedArticle,
        generator,
        topic: Topic,
        sources: List[SourceArticle]
    ) -> Tuple[Optional[AdaptedArticle], QualityResult]:
        """
        Check quality and regenerate if needed

        Args:
            article: Article to check
            generator: ContentGenerator instance (for regeneration)
            topic: Original topic dict
            sources: Original source content

        Returns:
            (final_article or None, quality_result)
        """
        attempt_history = []
        current_article = article
        level = article.level

        for attempt in range(1, self.max_attempts + 1):
            self.logger.info(f"Quality check attempt {attempt}/{self.max_attempts}")

            # Evaluate current version
            result_dict = self._evaluate(current_article) # _evaluate returns Dict for now

            attempt_history.append({
                'attempt': attempt,
                'score': result_dict['total_score'],
                'issues': result_dict['issues']
            })

            passed = result_dict['total_score'] >= self.min_score

            if passed:
                self.logger.info(f"✅ Passed on attempt {attempt} (score: {result_dict['total_score']:.1f}/{self.min_score})")
                return current_article, QualityResult(
                    passed=True,
                    score=result_dict['total_score'],
                    issues=[],
                    strengths=result_dict.get('strengths', []),
                    attempts=attempt,
                    grammar_score=result_dict.get('grammar_score'),
                    educational_score=result_dict.get('educational_score'),
                    content_score=result_dict.get('content_score'),
                    level_score=result_dict.get('level_score')
                )

            # Failed - should we try again?
            if attempt >= self.max_attempts:
                self.logger.warning(
                    f"❌ Failed after {attempt} attempts (final: {result_dict['total_score']:.1f}/{self.min_score})"
                )
                return None, QualityResult(
                    passed=False,
                    score=result_dict['total_score'],
                    issues=result_dict['issues'],
                    strengths=result_dict.get('strengths', []),
                    attempts=attempt,
                    grammar_score=result_dict.get('grammar_score'),
                    educational_score=result_dict.get('educational_score'),
                    content_score=result_dict.get('content_score'),
                    level_score=result_dict.get('level_score')
                )

            # Regenerate with feedback
            self.logger.info(
                f"🔄 Regenerating (attempt {attempt + 1}) - score was {result_dict['total_score']:.1f}/{self.min_score}"
            )
            self.logger.debug(f"   Issues: {', '.join(result_dict['issues'][:3])}")

            try:
                current_article = generator.regenerate_with_feedback(
                    topic=topic,
                    sources=sources,
                    level=level,
                    previous_attempt=current_article,
                    issues=result_dict['issues']
                )
            except Exception as e:
                self.logger.error(f"Regeneration failed: {e}")
                return None, QualityResult(
                    passed=False,
                    score=result_dict['total_score'],
                    issues=result_dict['issues'] + [f"Regeneration failed: {str(e)}"],
                    strengths=result_dict.get('strengths', []),
                    attempts=attempt,
                    grammar_score=result_dict.get('grammar_score'),
                    educational_score=result_dict.get('educational_score'),
                    content_score=result_dict.get('content_score'),
                    level_score=result_dict.get('level_score')
                )

        # Should not reach here, but just in case
        return None, QualityResult(
            passed=False,
            score=0,
            issues=["Maximum attempts exceeded"],
            strengths=[],
            attempts=self.max_attempts
        )

    def _evaluate(self, article: AdaptedArticle) -> Dict:
        """Evaluate article quality using LLM judge"""

        level = article.level

        # Get prompt from centralized prompts module
        prompt = prompts.get_quality_judge_prompt(article, level)

        try:
            response = self._call_llm(prompt)
            result = response.model_dump()

            # Log the evaluation
            self.logger.debug(f"Quality scores: {result}")

            return result

        except Exception as e:
            self.logger.error(f"Quality evaluation failed: {e}")
            # Return failing result
            return {
                'total_score': 0,
                'issues': [f"Evaluation error: {str(e)}"],
                'strengths': [],
                'grammar_score': 0,
                'educational_score': 0,
                'content_score': 0,
                'level_score': 0
            }

    def _call_llm(self, prompt: str) -> JudgeResponse:
        """Call LLM with prompt"""
        try:
            return cast(
                JudgeResponse,
                self.judge_chain.invoke(
                    {
                        'prompt': prompt,
                        'format_instructions': self.format_instructions,
                    }
                ),
            )
        except Exception as e:
            self.logger.error(f"LLM API call failed: {e}")
            raise
