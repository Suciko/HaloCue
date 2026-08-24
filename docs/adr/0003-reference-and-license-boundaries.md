# ADR-0003: Reference and license boundaries

- Status: accepted
- Date: 2026-08-24

## Decision

AzureArchive and ChatArchive reverse-engineering outputs, Blue Archive data,
Studio binaries, and the PyTorch/Vulkan package are external research inputs.
They are identified by provenance and hashes but are not copied into the source
tree. LingChat is an AGPL-3.0 reference and its implementation is not copied.

## Consequences

New adapters must be independently implemented and must document their allowed
inputs. Public builds run the existing clean-source and third-party notice
checks. Any uncertain license or asset provenance blocks publication until it is
resolved.
