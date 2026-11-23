# Application admin email the chatbot and guardrail refusals point users to.
SUPPORT_EMAIL = "emran@emranhossen.com"

# The single canonical refusal sentence — used by the guardrails, the agent's
# system prompt, and anywhere else the assistant declines a request.
REFUSAL_MESSAGE = (
    f"Sorry, I can't help with that. For assistance, contact our application admin at {SUPPORT_EMAIL}."
)
