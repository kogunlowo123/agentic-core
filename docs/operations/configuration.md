# Runtime configuration

`configs/providers.yaml` is committed once and deployed to every
environment. Deployment-specific values are `${NAME}` references resolved
from the process environment by `ProvidersConfig.from_file`. If any
referenced variable is unset or empty, loading fails with the full list of
missing names; nothing falls back to a default.

In Kubernetes, non-secret values come from a ConfigMap and secrets from the
platform secret store (External Secrets Operator or the Secrets Store CSI
driver). Where workload identity is available (IRSA or EKS Pod Identity for
Bedrock, GKE Workload Identity for Vertex AI, Entra Workload ID for Azure),
prefer it over static keys.

## Variables referenced by `configs/providers.yaml`

| Variable | Kind | Used by |
|---|---|---|
| `ANTHROPIC_API_KEY` | secret | claude |
| `CLAUDE_INPUT_USD_PER_MTOK`, `CLAUDE_OUTPUT_USD_PER_MTOK` | contracted price | claude |
| `AWS_REGION` | config | bedrock-claude, nova |
| `BEDROCK_CLAUDE_MODEL_ID` | config (model or inference profile ID enabled in the account) | bedrock-claude |
| `BEDROCK_CLAUDE_INPUT_USD_PER_MTOK`, `BEDROCK_CLAUDE_OUTPUT_USD_PER_MTOK` | contracted price | bedrock-claude |
| `NOVA_INPUT_USD_PER_MTOK`, `NOVA_OUTPUT_USD_PER_MTOK` | contracted price | nova |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_REGION` | config | azure-gpt |
| `AZURE_OPENAI_API_KEY` | secret | azure-gpt |
| `AZURE_GPT_INPUT_USD_PER_MTOK`, `AZURE_GPT_OUTPUT_USD_PER_MTOK` | contracted price | azure-gpt |
| `AZURE_AI_FOUNDRY_ENDPOINT` | config | phi |
| `AZURE_AI_FOUNDRY_API_KEY` | secret | phi |
| `PHI_INPUT_USD_PER_MTOK`, `PHI_OUTPUT_USD_PER_MTOK` | contracted price | phi |
| `GCP_PROJECT_ID`, `GCP_REGION` | config | gemini |
| `GCP_ACCESS_TOKEN` | secret (short-lived, from workload identity) | gemini |
| `GEMINI_INPUT_USD_PER_MTOK`, `GEMINI_OUTPUT_USD_PER_MTOK` | contracted price | gemini |

Bedrock credentials are not variables in this file; boto3 resolves them from
the standard AWS credential chain.

A deployment that does not use a provider removes its entry from the file
in that deployment's overlay rather than setting dummy values.
