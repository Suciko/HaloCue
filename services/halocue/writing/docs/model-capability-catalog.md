# Model capability data in 1.0

The model ID and protocol selected by the author determine the transport. A catalog entry is only a suggestion about limits; it does not prove that an account or a custom gateway can serve that model. Activation sends a small real request to the configured endpoint before saving the configuration.

The Settings UI resolves capability suggestions in this order:

1. Metadata returned by the configured provider's `/models` endpoint, when it includes limits for the exact selected model.
2. The on-demand [models.dev](https://models.dev/) catalog lookup for the exact model ID. The in-memory catalog refreshes after six hours; a failed refresh can retry after five minutes.
3. The small, versioned built-in catalog in `model_capabilities.py` when the online catalog is unavailable or has no match.

The author explicitly applies or edits suggested context, input and output limits. These values are saved with the model configuration and used by the same request-budget function for connection tests and writing calls. Unknown models keep blank capability fields and remain configurable. Changing a model does not carry over the previous model's limits. The lookup does not transmit an API key or manuscript text to models.dev.

When adding a new transport, update its protocol adapter and request tests separately from catalog data. When a model limit changes, prefer updating the upstream catalog or a narrowly sourced built-in entry over adding a second provider-specific UI list. The Settings UI must keep the source and uncertainty visible, especially for local and gateway deployments.

This follows the registry-baseline and user-override separation documented by [Cherry Studio](https://github.com/CherryHQ/cherry-studio/blob/main/docs/references/provider-model/provider-registry.md). HaloCue does not bundle or copy Cherry Studio's generated catalog.
