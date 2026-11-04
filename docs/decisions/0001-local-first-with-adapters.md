# 0001: Build local first, with every outside dependency behind an adapter

Status: accepted
Date: 2026-10-22

## Context

MeetMind must be shown at AWS re:Invent 2026 and submitted to a Meta AI hackathon. The owner has one Mac, an AWS account, and about five weeks. The product has hard latency targets (alert within 1 s, first answer line within 3 s) that cannot be known until the real pipeline runs. Spending on AWS before the pipeline is proven would burn money on an unproven design.

## Options considered

1. **Build on AWS from day one.** Real target numbers from the start, but every iteration costs money, and a bug in the design is discovered late and expensively.
2. **Build a local prototype, then rewrite for AWS.** Cheap to iterate, but the rewrite is a second project and the local version stops being the same app.
3. **Build the full app locally with free components, with every outside dependency behind an interface, then add AWS adapters.** Cheap to iterate, same code in both places, and the local version stays a working fallback demo.

## Decision

Option 3. Five interfaces at first (SpeechToText, LLM, Embeddings, Store, Auth), extended to seven by decision 0003 (DocumentParser, VectorStore). Each has a local adapter now and an AWS adapter in Phase 4, selected by an environment variable. Each interface has a contract test that every adapter must pass. Model names live only in config.

Local adapters: a benchmarked local streaming STT engine with Silero VAD, Ollama for models and embeddings, DynamoDB Local in Docker, single-user local auth. AWS adapters: Amazon Transcribe, Bedrock, DynamoDB, Cognito.

## Consequences

- No AWS resource and no paid API call before Phase 4.
- The app logic never names an engine. Switching to AWS is a configuration change plus new adapters.
- The local version runs on the owner's laptop as the fallback demo if the internet or AWS fails at the event.
- Local latency numbers are a baseline only. The gates are checked again on AWS in Phase 4.
- DynamoDB Local is used instead of SQLite so the database code is identical in both stages.
