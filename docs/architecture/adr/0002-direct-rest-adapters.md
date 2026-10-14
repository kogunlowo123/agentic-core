# ADR-0002: Call model vendors through thin REST adapters

- Status: Accepted
- Date: 2026-10-14

## Context

Each vendor publishes an SDK. Pulling all of them into every service adds
large transitive dependency trees, overlapping HTTP stacks and frequent
breaking releases, all of which widen the supply-chain surface that the
Grype and Trivy gates have to cover.

## Decision

Implement adapters directly against the documented wire formats using one
`httpx.AsyncClient` per provider:

| Adapter | Wire format | Covers |
|---|---|---|
| `AnthropicProvider` | Messages API | Claude |
| `OpenAICompatibleProvider` | Chat Completions | OpenAI GPT, Azure OpenAI, Azure AI Foundry (Phi), vLLM/TGI/Ollama (Llama) |
| `GeminiProvider` | generateContent | Gemini API, Vertex AI |
| `BedrockConverseProvider` | Bedrock Converse via boto3 | Nova, Llama, Claude and other Bedrock models |

Bedrock is the exception: request signing (SigV4) and credential discovery
(IRSA, EKS Pod Identity) are delegated to boto3 as an optional extra rather
than reimplemented.

## Consequences

- Small dependency footprint; one HTTP stack to configure for proxies, mTLS
  and timeouts.
- New vendor features (tool use, streaming, multimodal) need adapter work.
  The `ModelRequest`/`ModelResponse` contracts are versioned so this can be
  added without breaking callers.
- Adapters are tested against recorded wire shapes with `httpx.MockTransport`.
  Live-endpoint contract tests run in the integration stage of each service
  repository with real credentials from the CI secret store.
