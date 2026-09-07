"""Validate accepted reaction sidecars against an in-memory compiler result.

This is not a beat/resource authorization pass: callers supply already validated
beats and the same frozen cast, index and configuration used for export. No AA
metadata is added and no project, asset database or provider is opened.
"""

import document


class ReactionIntentError(ValueError):
    """An accepted reaction cannot be traced to its intended compiled result."""

    code = "reaction_intent_lost"

    def __init__(self, diagnostics: list[dict]):
        self.details = {"diagnostics": diagnostics}
        super().__init__("Reaction intent lost: " + "; ".join(d["message"] for d in diagnostics))


def _diagnostic(record, message):
    return {
        "severity": "error",
        "code": "reaction.intent_lost",
        "line_no": record.get("source_line"),
        "source_id": record.get("anchor_id"),
        "beat_id": record.get("beat_id"),
        "output_line": record.get("output_line"),
        "message": message,
    }


def _mapped_rows(nodes, events, scenes, cast):
    """Check the compiler's one-line/one-row contract, including scene boundaries."""
    expected = [
        node
        for node in nodes
        if node.kind == "line" and document.split_head(node.fields["who"], cast)[0] in cast
    ]
    lines = [event for event in events if event["k"] == "line"]
    if len(lines) != len(expected):
        raise ValueError("Invalid output mapping: parsed line/event counts differ")
    for node, event in zip(expected, lines):
        who = document.split_head(node.fields["who"], cast)[0]
        if (
            type(event.get("no")) is not int
            or event["no"] != node.line_no
            or event.get("who") != who
            or event.get("text") != node.fields["text"]
        ):
            raise ValueError("Invalid output mapping: event source line or target does not match")

    # build omits title events and scenes with no dialogue rows. Check per-scene
    # cardinality, not just a global zip which could silently shift beat identity.
    groups = []
    title, group = None, []
    for event in events:
        if event["k"] == "scene":
            if group:
                groups.append((title, group))
            title, group = event["title"], []
        elif event["k"] == "line":
            group.append(event)
    if group:
        groups.append((title, group))
    if len(groups) != len(scenes):
        raise ValueError("Invalid output mapping: compiled scene count differs")
    mapped = {}
    compiled_index = 0
    for (title, group), (compiled_title, rows) in zip(groups, scenes):
        if title != compiled_title or len(group) != len(rows):
            raise ValueError("Invalid output mapping: compiled scene/row counts differ")
        for event, row in zip(group, rows):
            if (
                not isinstance(row, dict)
                or row.get("text") != event["text"]
                or row.get("isDialogScript") is not True
            ):
                raise ValueError("Invalid output mapping: compiled dialogue row does not match")
            mapped[event["no"]] = (compiled_index, event, row)
            compiled_index += 1
    return mapped


def _requested_values(record, ident, idx, compiler):
    """Resolve using compiler semantics, but never treat its fallback as evidence."""
    emo_sym, emo_cn, act, act_cn, faces = compiler.res_lookup(idx)
    expected = {}
    no = record.get("source_line")
    if record.get("face"):
        value = compiler.resolve_face(record["face"], ident, faces, no)
        if value is None or value not in faces.get(ident, {}).get("ids", set()):
            raise ValueError(f"Requested face {record['face']!r} has no indexed target evidence")
        expected["faceId"] = ("face", value)
    for field, output, tables, resolve in (
        ("emo", "emoticon", (emo_sym, emo_cn), compiler.resolve_emo),
        ("act", "action", (act, act_cn), compiler.resolve_act),
    ):
        token = record.get(field)
        if not token:
            continue
        token = token.strip()
        # Explicit enumeration membership also covers indexed numeric IDs. Merely
        # looking numeric (or matching the compiler's no-op default) is insufficient.
        known = {str(key) for table in tables for key in table}
        known.update(str(value) for table in tables for value in table.values())
        if field == "emo":
            known.update(
                key[1:-1]
                for key in emo_sym
                if key.startswith(("[", "{")) and key.endswith(("]", "}"))
            )
        if token not in known:
            raise ValueError(f"Requested {field} {token!r} has no indexed evidence")
        expected[output] = (field, resolve(token, *tables, no))
    return expected


def validate_reaction_output(text, records, cast, idx, cfg) -> list[dict]:
    """Return copied sidecars with zero-based ``compiled_index``, or block export.

    ``output_line`` is a one-based rendered document line, not a dialogue ordinal.
    Normal/offscreen dialogue is not subject to reaction visibility requirements.
    Source anchors and beat authorization remain the caller's responsibility.
    """
    if not records:
        return []
    records = [dict(record) for record in records]
    try:
        nodes = document.parse_document_lossless(text)
        by_line = {node.line_no: node for node in nodes}
        diagnostics = []
        claimed = set()
        for record in records:
            line = record.get("output_line")
            who = record.get("who")
            character = cast.get(who, {})
            if (
                not character.get("portrait")
                or character.get("narrator")
                or not character.get("id")
            ):
                diagnostics.append(
                    _diagnostic(record, f"Unknown or non-portrait reaction target {who!r}")
                )
                continue
            if type(line) is not int or line not in by_line:
                diagnostics.append(
                    _diagnostic(
                        record, "Invalid output mapping: output_line must name a rendered line"
                    )
                )
                continue
            node = by_line[line]
            if node.kind != "line":
                diagnostics.append(
                    _diagnostic(
                        record, "Invalid output mapping: reaction marker is not a dialogue line"
                    )
                )
            elif document.split_head(node.fields["who"], cast)[0] != who:
                diagnostics.append(
                    _diagnostic(
                        record, "Rendered reaction target does not match the accepted target"
                    )
                )
            elif node.fields["text"] != "":
                diagnostics.append(
                    _diagnostic(record, "Rendered reaction must have empty dialogue")
                )
            if line in claimed:
                diagnostics.append(
                    _diagnostic(record, "Invalid output mapping: multiple reactions claim one line")
                )
            claimed.add(line)
        if diagnostics:
            raise ReactionIntentError(diagnostics)

        # Import lazily as well as compiling lazily: normal annotation must not
        # acquire compiler side effects just to validate an empty sidecar.
        import script2aap

        requested = {}
        for number, record in enumerate(records):
            try:
                requested[number] = _requested_values(
                    record, cast[record["who"]]["id"], idx, script2aap
                )
            except ValueError as exc:
                diagnostics.append(_diagnostic(record, str(exc)))
        if diagnostics:
            raise ReactionIntentError(diagnostics)

        events, compiler_diagnostics = document.compile_document(nodes, cast, idx)
        scenes = script2aap.build(events, cfg, cast, idx, "reaction-integrity")
        mapped = _mapped_rows(nodes, events, scenes, cast)
        for number, record in enumerate(records):
            line = record["output_line"]
            if line not in mapped:
                diagnostics.append(
                    _diagnostic(record, "Invalid output mapping: reaction has no compiled event")
                )
                continue
            compiled_index, _, row = mapped[line]
            for diagnostic in compiler_diagnostics:
                if diagnostic.get("severity") == "error" and diagnostic.get("line_no") == line:
                    diagnostics.append(
                        _diagnostic(record, f"Invalid reaction target: {diagnostic['message']}")
                    )
            ident = cast[record["who"]]["id"]
            chars = row.get("characters", {}).get("$values", [])
            targets = [char for char in chars[1:6] if char.get("name") == ident]
            if len(targets) != 1:
                diagnostics.append(
                    _diagnostic(
                        record,
                        f"Reaction target {record['who']!r} is not uniquely visible in portrait slots 1..5",
                    )
                )
                continue
            for field, (label, expected) in requested[number].items():
                actual = targets[0].get(field)
                if actual != expected:
                    diagnostics.append(
                        _diagnostic(
                            record,
                            f"Reaction {label} mismatch: expected {expected!r}, got {actual!r}",
                        )
                    )
            wait = record.get("wait_ms", 0)
            if (
                wait > 0
                and row.get("additionalPrompt", "").splitlines().count(f"#wait;{wait}") != 1
            ):
                diagnostics.append(
                    _diagnostic(
                        record, f"Reaction wait #{wait} must occur exactly once in additionalPrompt"
                    )
                )
            record["compiled_index"] = compiled_index
        if diagnostics:
            raise ReactionIntentError(diagnostics)
        return records
    except ReactionIntentError:
        raise
    except Exception as exc:
        raise ReactionIntentError(
            [
                _diagnostic(
                    record, f"Reaction compilation/mapping failed ({type(exc).__name__}): {exc}"
                )
                for record in records
            ]
        ) from exc
