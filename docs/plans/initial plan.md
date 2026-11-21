# Initial plan for the FastAPI and Groq assistant

1. Install the project dependencies with `uv sync --locked`.
2. Start the server with `uv run uvicorn main:app --reload`. Check `GET /health` and open `/docs`.
3. Set `GROQ_API_KEY` and `GROQ_MODEL` in the environment or a local .env file. Use a chat model ID available to your Groq account. Restart the server after configuring it.
4. Compile a single-node LangGraph workflow at startup. For each request, pass fresh message state to the assistant node, which calls Groq asynchronously.
5. Submit `{"message":"Hello"}` to `POST /chat` and verify the text in the reply field.
6. Use Logfire for request and graph timing. Set LOGFIRE_TOKEN to enable remote export.

## Acceptance checks

Verify health without credentials, successful independent requests with a fake model, validation of blank input, and HTTP 504 and 502 for timeout and provider errors. Run the live check after configuring credentials.
