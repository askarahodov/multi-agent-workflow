# Provider catalogue & compatible API connections

In **Настройки → Подключения**, choose OpenRouter, HuggingFace, Custom OpenAI-compatible or offline Mock. This maps to the existing agent-management provider adapters. For custom providers supply a trusted API base URL, usually ending in `/v1`; never enter a credential for an untrusted URL. The backend encrypts provider keys and never returns them in the UI.

When an active saved OpenRouter connection is selected in the **Модели** tab, agent-management performs a **read-only** GET to the official fixed `https://openrouter.ai/api/v1/models` catalogue. The response includes available model IDs, context limits, supported request parameters, provider-reported defaults and per-token price strings. The UI displays this metadata and can fill model ID/name and valid defaults for temperature and max output tokens. A separate Save action persists the selected model profile; discovery does not spend inference credits.

The fixed server-side endpoint ignores any customer-supplied `base_url` for discovery, preventing its use as an arbitrary URL proxy. OpenAI-compatible custom servers do not have a universally reliable model metadata schema; their model ID remains manually configurable. The catalogue may contain models unavailable to a particular account and prices can change. No claim is made that choosing a model proves live inference, budget enforcement or tool-call support. See #254 and #11 for execution acceptance.

Creating a provider selects the saved connection so its model catalog is fetched when opening the Models tab. Key rotation is available for all credential-bearing provider types; no key is echoed in the UI.
