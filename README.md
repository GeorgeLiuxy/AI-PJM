# AI-PJM

AI PJM is being evolved from an item analysis prototype into an AI-assisted engineering delivery orchestration platform.

Current v2 baseline documents:

- [v2 delivery blueprint](docs/v2-delivery-blueprint.md)
- [v2 localization glossary](docs/v2-localization-glossary.md)
- [v2 implementation plan](docs/v2-implementation-plan.md)
- [v2 interaction flow](docs/v2-interaction-flow.md)
- [v2 verification guide](docs/v2-verification-guide.md)

Current v2 backend framework:

- `/api/v2/demands`
- `/api/v2/demands/{id}/spec`
- `/api/v2/demands/{id}/repo-context`
- `/api/v2/demands/{id}/impact-analysis`
- `/api/v2/spec-cards/{id}/coding-task`
- `/api/v2/coding-tasks/{id}/runs`

The default workflow provider is `mock`. Dify/OpenAI providers and the real Codex execution worker are intentionally left as follow-up implementation slices.
