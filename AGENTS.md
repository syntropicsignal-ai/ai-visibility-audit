# Project conventions

## Comments and docstrings

Write comments and docstrings only for the non-obvious. Typed code with
descriptive names is self-documenting — add prose only when behaviour,
intent, or a constraint genuinely can't be inferred from the code
itself. Don't restate the signature, narrate what the next line does, or
explain *why we chose X*.

## Tests

**A test earns its place only if a plausible future change to the
codebase could break it in a way no other test would catch.** Don't
bloat the suite with AI-slop tests that exercise things Python or
the type system already guarantees.

Write a test when it does at least one of:

1. **Guards a public contract.** Function/class/route signatures, the
   shape of returned dataclasses, the keys in a response payload,
   schema invariants enforced at runtime.
2. **Pins non-obvious behavior.** Caching policy, retry-after-failure,
   fallback values, quality gates, cost-prevention short-circuits —
   anything where a future reader might "fix" the code in a way that
   silently breaks the intent.
3. **Catches data-quality regressions.** Hand-maintained catalog
   invariants (uniqueness, cross-references), enum/Literal coverage,
   migration shape checks.
4. **Regression guard for a real fix.** Tied to a specific bug that
   was fixed; the test fails on the buggy code and passes on the fix.

Do NOT write tests for:

- **Math primitives** the language or stdlib already provides
  (dot products on 3-element vectors, string `.upper()`, `dict.get`).
- **Dataclass defaults** (Python guarantees `field(default=X)` works).
- **Protocol `isinstance()` checks** on classes that already declare
  `class X(SomeProtocol)` — the declaration enforces it.
- **Single-row dict lookups** (`get_country("PL")` returns the PL row).
  If `dict.get` is broken we have bigger problems.
- **Wire-up trivia** (does kwarg X reach kwarg Y in a one-line passthrough).
- **Implementation-detail warnings** that no caller acts on.

When in doubt: don't write the test. A small, sharp suite of contract
tests is more valuable than a large suite where most cases test the
language or the framework.
