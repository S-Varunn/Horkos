import json
import logging
import re
from typing import Optional, Dict, Any
from openai import AsyncOpenAI
from config import settings

logger = logging.getLogger("CommitmentRadar.LLM")


class LLMClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key or settings.llm_api_key or "dummy-key-for-local"
        self.model = model or settings.llm_model
        
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1
    ) -> Dict[str, Any]:
        """
        Sends a request to the Hermes / OpenAI-compatible endpoint and extracts JSON.
        Handles both direct JSON and markdown-wrapped ```json ``` blocks.
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,
                response_format={"type": "json_object"} if "ollama" not in self.base_url else None
            )

            raw_content = response.choices[0].message.content or ""
            return self._parse_json_from_response(raw_content)
        except Exception as e:
            logger.error(f"Error calling LLM at {self.base_url} with model {self.model}: {e}")
            raise

    def _parse_json_from_response(self, text: str) -> Dict[str, Any]:
        """Robustly extracts JSON from raw LLM output."""
        text = text.strip()
        # Direct parse attempt
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Check for ```json ... ``` block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Fallback regex search for innermost or outermost { ... }
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse valid JSON from LLM response: {text[:200]}")
