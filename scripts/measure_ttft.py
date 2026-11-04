"""Measure time to first token for the Ollama models MeetMind plans to use.

Run from the repo root with Ollama serving:
    python3.12 scripts/measure_ttft.py

Only the standard library is needed. For each chat model we measure a cold call
(model not loaded) and a warm call, and we check that the classifier candidates
return valid JSON for the Detector B schema. For the embedding model we time
one embedding call.

Note on builds: on Apple silicon the default qwen3.5 tags resolve to MLX builds,
and Ollama's MLX runner does not support schema-constrained output ("format").
Slots that need strict JSON must use a GGUF build such as the -q4_K_M tags.
"""

import json
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

CLASSIFIER_CANDIDATES = ["qwen3.5:4b-q4_K_M", "llama3.2:3b"]
ANSWER_CANDIDATES = ["qwen3.5:9b-q4_K_M", "llama3.1:8b"]
EMBED_MODELS = ["nomic-embed-text"]

ANSWER_PROMPT = "In one sentence, what does a load balancer do?"

# The same shape Detector B will use in Step 1.8.
CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "is_question": {"type": "boolean"},
        "directed_to_user": {"type": "boolean"},
        "question_text": {"type": "string"},
        "category": {"type": "string", "enum": ["small_talk", "technical", "logistics", "other"]},
        "confidence": {"type": "number"},
    },
    "required": ["is_question", "directed_to_user", "question_text", "category", "confidence"],
}
CLASSIFIER_PROMPT = (
    "The user is Surya, a junior ML engineer. Aliases: Surya, Sur.\n"
    "Transcript of the last few seconds (them):\n"
    "\"Okay so the eval numbers look fine. Surya, what batch size did you end up using for the last run?\"\n"
    "Classify the last sentence."
)


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req)


def capabilities(model):
    with post("/api/show", {"model": model}) as resp:
        return json.load(resp).get("capabilities", [])


def unload(model):
    with post("/api/generate", {"model": model, "keep_alive": 0}):
        pass


def stream_chat(model, prompt, schema=None):
    """Send one chat request, stream it, and return what we measured.

    Returns a dict with seconds to first token, tokens per second,
    model load seconds, and the full reply text.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": {"num_predict": 200, "temperature": 0},
    }
    if "thinking" in capabilities(model):
        body["think"] = False
    if schema:
        body["format"] = schema

    start = time.perf_counter()
    first_token_at = None
    text = ""
    with post("/api/chat", body) as resp:
        for line in resp:
            chunk = json.loads(line)
            piece = chunk["message"].get("content", "")
            if piece and first_token_at is None:
                first_token_at = time.perf_counter() - start
            text += piece
            if chunk.get("done"):
                tokens_per_second = chunk["eval_count"] / (chunk["eval_duration"] / 1e9)
                load_seconds = chunk["load_duration"] / 1e9
    return {
        "ttft": first_token_at,
        "tps": tokens_per_second,
        "load": load_seconds,
        "text": text,
    }


def measure_chat(model, prompt, schema=None):
    unload(model)
    cold = stream_chat(model, prompt, schema)
    warm = stream_chat(model, prompt, schema)
    return cold, warm


def measure_embed(model):
    unload(model)
    start = time.perf_counter()
    with post("/api/embed", {"model": model, "input": ANSWER_PROMPT}) as resp:
        result = json.load(resp)
    cold = time.perf_counter() - start
    start = time.perf_counter()
    with post("/api/embed", {"model": model, "input": ANSWER_PROMPT}):
        pass
    warm = time.perf_counter() - start
    return cold, warm, len(result["embeddings"][0])


def main():
    print(f"{'model':<18}{'role':<12}{'cold ttft':>10}{'warm ttft':>10}{'tok/s':>8}{'load':>7}  note")
    for model in CLASSIFIER_CANDIDATES:
        cold, warm = measure_chat(model, CLASSIFIER_PROMPT, CLASSIFIER_SCHEMA)
        try:
            parsed = json.loads(warm["text"])
            note = f"json ok, directed_to_user={parsed['directed_to_user']}, category={parsed['category']}"
        except (json.JSONDecodeError, KeyError) as error:
            note = f"JSON FAILED: {error}: {warm['text'][:80]}"
        print(f"{model:<18}{'classifier':<12}{cold['ttft']:>9.2f}s{warm['ttft']:>9.2f}s{warm['tps']:>8.1f}{cold['load']:>6.1f}s  {note}")

    for model in ANSWER_CANDIDATES:
        cold, warm = measure_chat(model, ANSWER_PROMPT)
        note = warm["text"].strip().replace("\n", " ")[:70]
        print(f"{model:<18}{'answer':<12}{cold['ttft']:>9.2f}s{warm['ttft']:>9.2f}s{warm['tps']:>8.1f}{cold['load']:>6.1f}s  {note}")

    for model in EMBED_MODELS:
        cold, warm, dims = measure_embed(model)
        print(f"{model:<18}{'embeddings':<12}{cold:>9.2f}s{warm:>9.2f}s{'':>8}{'':>7}  {dims} dimensions")


if __name__ == "__main__":
    main()
