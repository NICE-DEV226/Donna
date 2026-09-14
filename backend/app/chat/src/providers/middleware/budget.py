"""Middleware budget : plafonne les tokens d'entrée d'un appel LLM."""

from __future__ import annotations

from ...usage import estimate_messages_tokens
from .base import BudgetExceededError, LLMContext, LLMMiddleware


class BudgetMiddleware(LLMMiddleware):
    """
    Vérifie AVANT l'appel que le volume estimé (messages + schéma d'outils)
    ne dépasse pas le plafond configuré. Dépasse une fois sur les rounds
    d'appels d'outils quand les résultats sont longs — la gestion est
    d'ailleurs déjà faite par le cap outil côté tools.py (plafonnement des
    résultats réinjectés). Ici c'est le garde-fou final.

    Lève BudgetExceededError : l'appelant transforme ça en réponse aimable,
    jamais en erreur 500.
    """

    def __init__(self, max_tokens_per_call: int) -> None:
        super().__init__()
        self._max_tokens = int(max_tokens_per_call)
        self.name = "budget"

    def _estimate_input(self, ctx: LLMContext) -> int:
        # Les images ont un coût fixe forfaitaire par image (approximation).
        images_cost = sum(512 for _ in ctx.images_b64 or [])
        return estimate_messages_tokens(ctx.messages, ctx.tools) + images_cost

    async def before(self, ctx: LLMContext) -> None:
        ctx.input_tokens = self._estimate_input(ctx)
        if ctx.input_tokens > self._max_tokens:
            raise BudgetExceededError(
                f"budget tokens dépassé ({ctx.input_tokens} > {self._max_tokens}) pour '{ctx.provider}'"
            )