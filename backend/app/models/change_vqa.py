"""
Change VQA Model Stub — Placeholder for bi-temporal question answering.

Owner: M4 (ML Pipelines Lead)
Status: STUB — returns 'Model output not available'.

In production: reuses Qwen2.5-VL with 2 images + change context.
"""

from loguru import logger

from app.models.base import BaseModelWrapper
from app.utils.synthesize import synthesize_answer


class ChangeVQAModel(BaseModelWrapper):
    """
    Stub: Change VQA — answers specific questions about detected changes.

    In the real implementation, this would feed 2 images + change map
    to Qwen2.5-VL for bi-temporal question answering.

    TODO (M4): Replace with actual Qwen multi-image inference + change context.
    """

    def run(self, action: str, context: dict) -> dict:
        query = context["query"]
        # Bi-temporal by definition. This stub never indexes the list, but the
        # declared arity is enforced here too so a real implementation cannot
        # inherit a one-image context from a text-only routing decision.
        images = self.require_images(
            context, 2, model="change_vqa", action=action
        )

        logger.info(f"[STUB] Change VQA answering: '{query[:50]}...'")

        return {
            "answer": synthesize_answer(query, images, "change"),
            "confidence": None,
        }
