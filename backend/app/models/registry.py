"""
ModelRegistry — Load/unload/get models with automatic VRAM management.

Handles the RTX 4060 (8GB) constraint by loading ONE major model at a time.
Strategy: Load → Infer → (auto-unload if needed) → Load next.
"""

import gc
from loguru import logger


class ModelRegistry:
    """
    Central registry for all model wrappers.

    Models are registered with a lazy loader function and VRAM estimate.
    When a model is requested, the registry:
      1. Checks if it's already loaded
      2. If not, ensures enough VRAM by unloading other models
      3. Loads the model via its loader function
      4. Returns the loaded model instance
    """

    def __init__(self):
        self._models: dict = {}      # name → loaded model instance
        self._configs: dict = {}     # name → {"loader": fn, "vram_gb": float}

    def register(self, name: str, loader_fn, vram_gb: float = 0.0):
        """
        Register a model with a lazy loader.

        Args:
            name: Unique model identifier (e.g. "rs_vlm", "grounding_dino").
            loader_fn: Callable that returns a model instance when called.
            vram_gb: Estimated VRAM usage in GB.
        """
        self._configs[name] = {"loader": loader_fn, "vram_gb": vram_gb}
        logger.debug(f"Registered model: {name} (~{vram_gb} GB)")

    def get(self, name: str):
        """
        Get a loaded model instance. Loads it if not already loaded.

        Auto-unloads other models if VRAM is insufficient.

        Args:
            name: Model identifier.

        Returns:
            Loaded model wrapper instance.

        Raises:
            ValueError: If model name is not registered.
        """
        if name not in self._configs:
            raise ValueError(
                f"Unknown model: '{name}'. "
                f"Registered models: {list(self._configs.keys())}"
            )

        if name not in self._models:
            self._load(name)

        return self._models[name]

    def _load(self, name: str):
        """Load a model, ensuring VRAM is available first."""
        config = self._configs[name]
        needed_gb = config["vram_gb"]

        # Free up VRAM if needed
        self._ensure_vram(needed_gb, exclude=name)

        logger.info(f"Loading model: {name} (~{needed_gb} GB)")
        try:
            self._models[name] = config["loader"]()
            logger.info(f"Model loaded: {name}")
        except Exception as e:
            logger.error(f"Failed to load model {name}: {e}")
            raise

    def _ensure_vram(self, needed_gb: float, exclude: str = ""):
        """Unload models until enough VRAM is free.

        Uses `torch.cuda.mem_get_info()`, which reports the driver's real
        free/total figures. The previous `total_memory - memory_allocated()`
        was wrong twice over: `memory_allocated()` counts only PyTorch's
        live tensors (ignoring its own cached reserve and every other
        process on the GPU), and the attribute was misspelled `total_mem`,
        which raised AttributeError on any actual CUDA box — and since only
        ImportError is caught below, that escaped `_load()` and made every
        model load fail.
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return

            free = torch.cuda.mem_get_info()[0] / 1e9

            while free < needed_gb and self._models:
                # Unload the oldest loaded model (FIFO)
                candidates = [k for k in self._models if k != exclude]
                if not candidates:
                    break
                oldest = candidates[0]
                self.unload(oldest)
                free = torch.cuda.mem_get_info()[0] / 1e9

        except ImportError:
            # No torch — CPU mode, nothing to manage.
            pass
        except Exception as e:
            # A CUDA query can fail for reasons that have nothing to do with
            # this model: a poisoned context, a post-fork process, a driver
            # mismatch. Previously only ImportError was caught, so such a
            # RuntimeError escaped _ensure_vram → escaped _load → and every
            # subsequent load failed for the process lifetime with a raw CUDA
            # string. Degrade to "skip VRAM management" and let the load
            # attempt proceed; if there genuinely isn't room, the loader's own
            # OOM is the accurate error.
            logger.warning(f"VRAM check failed ({e}); proceeding without eviction.")

    def unload(self, name: str):
        """Unload a model and free its resources."""
        if name in self._models:
            del self._models[name]
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info(f"Unloaded model: {name}")

    def unload_all(self):
        """Unload all loaded models."""
        for name in list(self._models.keys()):
            self.unload(name)

    def list_loaded(self) -> list[str]:
        """Return names of currently loaded models."""
        return list(self._models.keys())

    def list_all(self) -> list[dict]:
        """Return info about all registered models."""
        return [
            {
                "name": name,
                "loaded": name in self._models,
                "vram_gb": config["vram_gb"],
            }
            for name, config in self._configs.items()
        ]

    def describe(self, name: str) -> dict:
        """Registry facts about a model, whether or not it is registered.

        Used by the execution trace instead of inventing metadata. There is
        deliberately no capability/description data here: the registry stores
        only a loader and a VRAM estimate, so anything richer would be made
        up. `version` reads whatever the wrapper instance declares — None for
        every wrapper today, and it lights up on its own the day one sets it.

        `registered: False` is meaningful: the router hardcodes model-name
        literals, so a rename in main.py surfaces here rather than as an
        unexplained step failure.
        """
        config = self._configs.get(name)
        return {
            "registered": config is not None,
            "loaded": name in self._models,
            "vram_gb": config["vram_gb"] if config else None,
            "version": getattr(self._models.get(name), "version", None),
        }
