"""
VQA Model Wrapper — Qwen2.5-VL-7B-Instruct-AWQ integration.

Supports actions:
  - answer_question: Single-image VQA
  - generate_caption: RS-specific captioning
  - describe_changes: Bi-temporal change description (2 images)
  - analyze_fused: Post-fusion analysis

Falls back to returning 'Model output not available' when Qwen model is not available (no GPU / weights not downloaded).
"""

import os
from pathlib import Path

from loguru import logger

from app.models.base import BaseModelWrapper
from app.utils.config import settings
from app.utils.synthesize import synthesize_answer


class QwenVLMWrapper(BaseModelWrapper):
    """
    Wrapper around Qwen2.5-VL-7B-Instruct-AWQ for satellite image understanding.

    On GPU with downloaded weights: runs real Qwen inference.
    On CPU / no weights: returns 'Model output not available' for testing.
    """

    def __init__(self):
        self.model = None
        self.processor = None
        self.device = "cpu"
        self._mock_mode = False

        self._try_load_model()

    def _try_load_model(self):
        """Attempt to load Qwen2.5-VL. Fall back to mock mode if unavailable."""
        model_path = settings.QWEN_MODEL_PATH

        if not Path(model_path).exists():
            logger.warning(
                "Qwen model path not found or empty. "
                "Running in NO OUTPUT MODE — 'Model output not available' will be returned."
            )
            self._mock_mode = True
            return

        try:
            import torch
            from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

            device = "cuda" if torch.cuda.is_available() else "cpu"

            logger.info(f"Loading Qwen2.5-VL from {model_path} on {device}...")

            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_path,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None,
            )

            self.processor = AutoProcessor.from_pretrained(
                model_path,
                min_pixels=256 * 28 * 28,
                max_pixels=1280 * 28 * 28,
            )

            self.device = device
            logger.info(f"Qwen2.5-VL loaded successfully on {device}")

        except Exception as e:
            logger.warning(f"Failed to load Qwen model: {e}. Using NO OUTPUT MODE.")
            self._mock_mode = True

    def run(self, action: str, context: dict) -> dict:
        """
        Run VLM inference for the given action.

        Args:
            action: One of "answer_question", "generate_caption",
                    "describe_changes", "analyze_fused"
            context: Pipeline context dict.

        Returns:
            Dict with "answer" and "confidence" keys.
        """
        if self._mock_mode:
            return self._mock_run(action, context)

        if action == "answer_question":
            return self._vqa(context)
        elif action == "generate_caption":
            return self._caption(context)
        elif action == "describe_changes":
            return self._describe_changes(context)
        elif action == "analyze_fused":
            return self._analyze_fused(context)
        else:
            raise ValueError(f"Unknown action for VQA model: '{action}'")

    # ── Real inference methods ──

    def _vqa(self, context: dict) -> dict:
        """Single-image Visual Question Answering (or a conversational reply
        when no image was attached — routed here for text-only queries)."""
        images = context["images"]
        query = context["query"]

        if not images:
            return {"answer": synthesize_answer(query, [], "vqa"), "confidence": 0.3}

        image_path = images[0]

        prompt = (
            "You are a remote sensing expert analyzing satellite imagery. "
            f"Look at this satellite image carefully and answer: {query}\n"
            "Provide a detailed, specific answer using remote sensing terminology."
        )

        answer = self._infer_single(image_path, prompt)
        return {"answer": answer, "confidence": self._estimate_confidence(answer)}

    def _caption(self, context: dict) -> dict:
        """Generate detailed RS caption."""
        image_path = context["images"][0]

        prompt = (
            "You are a remote sensing expert. Provide a detailed description "
            "of this satellite image. Include:\n"
            "1. Land cover types visible (urban, vegetation, water, bare soil, etc.)\n"
            "2. Notable structures or features\n"
            "3. Spatial layout and patterns\n"
            "4. Approximate scale and resolution observations\n"
            "Be specific and use remote sensing terminology."
        )

        answer = self._infer_single(image_path, prompt)
        return {"answer": answer, "confidence": self._estimate_confidence(answer)}

    def _describe_changes(self, context: dict) -> dict:
        """Bi-temporal change description using 2 images."""
        images = context["images"]
        query = context["query"]
        change_info = context.get("intermediate", {}).get("step_1", {})

        # Build change context string
        change_context = ""
        if change_info:
            ratio = change_info.get("change_ratio", 0)
            change_context = (
                f"\nA change detection algorithm found that approximately "
                f"{ratio * 100:.1f}% of the area has changed."
            )

        prompt = (
            "You are a remote sensing expert. You are shown two satellite images "
            "of the same area taken at different times. The first image is the earlier "
            "date and the second image is the later date.\n"
            f"{change_context}\n"
            f"Question: {query}\n"
            "Describe the changes you observe in detail, mentioning specific land cover "
            "transitions (e.g., vegetation to built-up, water body expansion, etc.)."
        )

        answer = self._infer_multi(images, prompt)
        return {"answer": answer, "confidence": self._estimate_confidence(answer)}

    def _analyze_fused(self, context: dict) -> dict:
        """Analyze result after optical-SAR fusion."""
        images = context["images"]
        query = context["query"]
        fusion_info = context.get("intermediate", {}).get("step_1", {})

        # Build fusion context string
        fusion_context = ""
        if fusion_info:
            classes = fusion_info.get("classes", {})
            if classes:
                class_str = ", ".join(
                    f"{name}: {pct}%" for name, pct in classes.items()
                )
                fusion_context = (
                    f"\nA fusion analysis detected these land cover classes: {class_str}"
                )

        prompt = (
            "You are a remote sensing expert. You are analyzing satellite data "
            "that combines optical imagery (showing spectral/color information) "
            "and SAR imagery (showing structural/moisture information).\n"
            f"{fusion_context}\n"
            f"Question: {query}\n"
            "Provide a comprehensive analysis using both optical and SAR perspectives."
        )

        answer = self._infer_multi(images, prompt)
        return {"answer": answer, "confidence": self._estimate_confidence(answer)}

    # ── Core Qwen inference ──

    def _infer_single(self, image_path: str, prompt: str) -> str:
        """Run Qwen inference with a single image."""
        from qwen_vl_utils import process_vision_info

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": f"file://{os.path.abspath(image_path)}"},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        return self._run_qwen_inference(messages)

    def _infer_multi(self, image_paths: list[str], prompt: str) -> str:
        """Run Qwen inference with multiple images."""
        from qwen_vl_utils import process_vision_info

        content = []
        for i, path in enumerate(image_paths):
            content.append(
                {"type": "image", "image": f"file://{os.path.abspath(path)}"}
            )

        content.append({"type": "text", "text": prompt})

        messages = [{"role": "user", "content": content}]

        return self._run_qwen_inference(messages)

    def _run_qwen_inference(self, messages: list[dict]) -> str:
        """Execute Qwen2.5-VL inference and return generated text."""
        import torch
        from qwen_vl_utils import process_vision_info

        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        # Trim input tokens from output
        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        output_text = self.processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

        return output_text[0].strip() if output_text else "Unable to generate response."

    # ── Confidence estimation ──

    def _estimate_confidence(self, answer: str) -> float:
        """
        Heuristic confidence based on answer characteristics.
        Longer, more detailed answers suggest higher confidence.
        """
        if not answer:
            return 0.3

        words = len(answer.split())
        if words > 50:
            return 0.88
        elif words > 30:
            return 0.82
        elif words > 15:
            return 0.75
        elif words > 5:
            return 0.65
        return 0.50

    # ── No Output mode (no GPU / no weights) ──

    def _mock_run(self, action: str, context: dict) -> dict:
        """Synthesize a dynamic, input-aware placeholder when the real model
        cannot be loaded, instead of a fixed 'Model output not available'."""
        task_hint = {
            "answer_question": "vqa",
            "generate_caption": "caption",
            "describe_changes": "change",
            "analyze_fused": "fusion",
        }.get(action, "vqa")

        answer = synthesize_answer(context["query"], context["images"], task_hint)
        logger.info(f"[NO OUTPUT MODE] Synthesized placeholder for action: {action}")
        # Fixed low confidence regardless of text length — this is a templated
        # placeholder, not a real model output, so word-count heuristics would
        # be misleading here.
        return {"answer": answer, "confidence": 0.3}
