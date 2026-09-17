"""The per-repository manifest that drives the harness.

A manifest is a JSON document. It declares everything the harness needs to
know about one repository's observable behaviour: which commands define its
CLI, which modules define its public interface, and which modules and test
command define its mutation-testing surface. Nothing in the harness infers
any of this; an undeclared invocation, module or scrub rule is simply not
checked.

Schema (top level, all paths are relative to the tree root, forward-slash
separated regardless of host OS)::

    {
      "schema_version": 1,

      // Optional. Seconds. Used for any invocation or test command that
      // does not declare its own "timeout". Defaults to 30.0 if omitted.
      "default_timeout": 30.0,

      // CLI byte differential: each entry is one subprocess invocation
      // whose exit code, stdout and stderr are captured as bytes and
      // compared byte for byte between baseline and candidate.
      "invocations": [
        {
          "id": "help",                       // required, unique, stable
          "argv": ["-m", "pkg", "--help"],     // required, passed to
                                                // sys.executable -- do not
                                                // include the interpreter
          "cwd": ".",                          // optional, default "."
          "env": {"MYVAR": "1"},               // optional overlay, on top
                                                // of the fixed determinism
                                                // overlay (see below)
          "expected_exit_code": 0,             // optional, informational
          "timeout": 10.0                      // optional, seconds
        }
      ],

      // Public-interface snapshot: source files parsed with `ast`, never
      // imported. Path to each module's source file, relative to the tree
      // root.
      "interface_modules": ["src/pkg/core.py"],

      // Mutation testing.
      "mutation": {
        "target_modules": ["src/pkg/core.py"],  // files mutated
        "test_command": {                       // run once per mutant;
          "argv": ["-m", "unittest", "discover"],// non-zero or timeout
          "cwd": ".",                             // means "killed"
          "env": {},
          "timeout": 30.0
        },
        "max_mutants": 200,           // optional cap: the first N sites in
                                       // deterministic order are run, never
                                       // a random sample (see
                                       // declutter.harness.mutation)
        "kill_rate_tolerance": 0.0    // optional, default 0.0: how far the
                                       // candidate kill rate may fall below
                                       // the baseline rate, per qualified
                                       // name, before it is a rejection
      },

      // Scrub rules: explicit, declared normalisation of genuine
      // nondeterminism (a temp path, a duration, a version banner) in
      // captured stdout/stderr, applied identically to baseline and
      // candidate output before comparison. Nothing is scrubbed
      // implicitly. Both fields are regex and replacement text, applied
      // with `re.sub` on the raw output bytes (encoded/decoded as UTF-8),
      // and echoed back in every report so a reader can see what was
      // hidden.
      "scrub_rules": [
        {"pattern": "tmp[a-z0-9]{8}", "replacement": "<tmp>"}
      ]
    }

Only ``schema_version`` and ``invocations``/``interface_modules``/
``mutation`` need not all be present at once -- a manifest that declares no
mutation target simply runs an empty mutation phase -- but each section
present must be well-formed. `schema_version` must currently be `1`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import HarnessError

DEFAULT_TIMEOUT = 30.0
SUPPORTED_SCHEMA_VERSION = 1


class ManifestError(HarnessError):
    """The manifest JSON does not match the schema documented above."""


@dataclass(frozen=True)
class ScrubRule:
    pattern: str
    replacement: str


@dataclass(frozen=True)
class Invocation:
    id: str
    argv: tuple[str, ...]
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    expected_exit_code: int | None = None
    timeout: float | None = None

    def env_dict(self) -> dict[str, str]:
        return dict(self.env)


@dataclass(frozen=True)
class TestCommand:
    argv: tuple[str, ...]
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    timeout: float | None = None

    def env_dict(self) -> dict[str, str]:
        return dict(self.env)


@dataclass(frozen=True)
class MutationConfig:
    target_modules: tuple[str, ...] = ()
    test_command: TestCommand | None = None
    max_mutants: int | None = None
    kill_rate_tolerance: float = 0.0


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    default_timeout: float
    invocations: tuple[Invocation, ...]
    interface_modules: tuple[str, ...]
    mutation: MutationConfig
    scrub_rules: tuple[ScrubRule, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _as_env_tuple(raw: object, where: str) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    _require(isinstance(raw, dict), f"{where}: 'env' must be an object")
    items = []
    for key, value in raw.items():  # type: ignore[union-attr]
        _require(isinstance(key, str), f"{where}: env keys must be strings")
        _require(isinstance(value, str), f"{where}: env values must be strings")
        items.append((key, value))
    return tuple(sorted(items))


def _as_argv(raw: object, where: str) -> tuple[str, ...]:
    _require(isinstance(raw, list) and len(raw) > 0, f"{where}: 'argv' must be a non-empty array")
    for item in raw:  # type: ignore[union-attr]
        _require(isinstance(item, str), f"{where}: every argv element must be a string")
    return tuple(raw)  # type: ignore[arg-type]


def _parse_invocation(raw: object, index: int) -> Invocation:
    where = f"invocations[{index}]"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    assert isinstance(raw, dict)
    _require(isinstance(raw.get("id"), str) and raw["id"], f"{where}: 'id' is required")
    argv = _as_argv(raw.get("argv"), where)
    cwd = raw.get("cwd", ".")
    _require(isinstance(cwd, str), f"{where}: 'cwd' must be a string")
    env = _as_env_tuple(raw.get("env"), where)
    expected_exit_code = raw.get("expected_exit_code")
    _require(
        expected_exit_code is None or isinstance(expected_exit_code, int),
        f"{where}: 'expected_exit_code' must be an integer",
    )
    timeout = raw.get("timeout")
    _require(
        timeout is None or isinstance(timeout, (int, float)),
        f"{where}: 'timeout' must be a number",
    )
    return Invocation(
        id=raw["id"],
        argv=argv,
        cwd=cwd,
        env=env,
        expected_exit_code=expected_exit_code,
        timeout=float(timeout) if timeout is not None else None,
    )


def _parse_test_command(raw: object, where: str) -> TestCommand:
    _require(isinstance(raw, dict), f"{where}: 'test_command' must be an object")
    assert isinstance(raw, dict)
    argv = _as_argv(raw.get("argv"), where)
    cwd = raw.get("cwd", ".")
    _require(isinstance(cwd, str), f"{where}: 'cwd' must be a string")
    env = _as_env_tuple(raw.get("env"), where)
    timeout = raw.get("timeout")
    _require(
        timeout is None or isinstance(timeout, (int, float)),
        f"{where}: 'timeout' must be a number",
    )
    return TestCommand(
        argv=argv,
        cwd=cwd,
        env=env,
        timeout=float(timeout) if timeout is not None else None,
    )


def _parse_mutation(raw: object) -> MutationConfig:
    if raw is None:
        return MutationConfig()
    where = "mutation"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    assert isinstance(raw, dict)
    target_modules_raw = raw.get("target_modules", [])
    _require(isinstance(target_modules_raw, list), f"{where}: 'target_modules' must be an array")
    for item in target_modules_raw:
        _require(isinstance(item, str), f"{where}: every target module must be a string")
    target_modules = tuple(target_modules_raw)

    test_command = None
    if target_modules:
        _require("test_command" in raw, f"{where}: 'test_command' is required when 'target_modules' is non-empty")
        test_command = _parse_test_command(raw["test_command"], where)
    elif "test_command" in raw:
        test_command = _parse_test_command(raw["test_command"], where)

    max_mutants = raw.get("max_mutants")
    _require(
        max_mutants is None or (isinstance(max_mutants, int) and max_mutants >= 0),
        f"{where}: 'max_mutants' must be a non-negative integer",
    )

    tolerance = raw.get("kill_rate_tolerance", 0.0)
    _require(
        isinstance(tolerance, (int, float)),
        f"{where}: 'kill_rate_tolerance' must be a number",
    )

    return MutationConfig(
        target_modules=target_modules,
        test_command=test_command,
        max_mutants=max_mutants,
        kill_rate_tolerance=float(tolerance),
    )


def _parse_scrub_rule(raw: object, index: int) -> ScrubRule:
    where = f"scrub_rules[{index}]"
    _require(isinstance(raw, dict), f"{where}: must be an object")
    assert isinstance(raw, dict)
    _require(isinstance(raw.get("pattern"), str), f"{where}: 'pattern' must be a string")
    _require(isinstance(raw.get("replacement"), str), f"{where}: 'replacement' must be a string")
    return ScrubRule(pattern=raw["pattern"], replacement=raw["replacement"])


def parse_manifest(data: object) -> Manifest:
    """Parse and validate a manifest already loaded from JSON.

    Raises `ManifestError` (a `HarnessError`) on any schema violation.
    """
    _require(isinstance(data, dict), "manifest: top level must be an object")
    assert isinstance(data, dict)

    schema_version = data.get("schema_version")
    _require(
        schema_version == SUPPORTED_SCHEMA_VERSION,
        f"manifest: 'schema_version' must be {SUPPORTED_SCHEMA_VERSION}, got {schema_version!r}",
    )

    default_timeout = data.get("default_timeout", DEFAULT_TIMEOUT)
    _require(
        isinstance(default_timeout, (int, float)) and default_timeout > 0,
        "manifest: 'default_timeout' must be a positive number",
    )

    invocations_raw = data.get("invocations", [])
    _require(isinstance(invocations_raw, list), "manifest: 'invocations' must be an array")
    invocations = tuple(_parse_invocation(raw, i) for i, raw in enumerate(invocations_raw))
    ids = [inv.id for inv in invocations]
    _require(len(ids) == len(set(ids)), "manifest: invocation ids must be unique")

    interface_modules_raw = data.get("interface_modules", [])
    _require(isinstance(interface_modules_raw, list), "manifest: 'interface_modules' must be an array")
    for item in interface_modules_raw:
        _require(isinstance(item, str), "manifest: every interface module must be a string")
    interface_modules = tuple(interface_modules_raw)

    mutation = _parse_mutation(data.get("mutation"))

    scrub_rules_raw = data.get("scrub_rules", [])
    _require(isinstance(scrub_rules_raw, list), "manifest: 'scrub_rules' must be an array")
    scrub_rules = tuple(_parse_scrub_rule(raw, i) for i, raw in enumerate(scrub_rules_raw))

    return Manifest(
        schema_version=schema_version,
        default_timeout=float(default_timeout),
        invocations=invocations,
        interface_modules=interface_modules,
        mutation=mutation,
        scrub_rules=scrub_rules,
    )


def manifest_to_dict(manifest: Manifest) -> dict:
    """Render a `Manifest` back to a plain dict, for embedding in artefacts."""
    return {
        "schema_version": manifest.schema_version,
        "default_timeout": manifest.default_timeout,
        "invocations": [
            {
                "id": inv.id,
                "argv": list(inv.argv),
                "cwd": inv.cwd,
                "env": dict(inv.env),
                "expected_exit_code": inv.expected_exit_code,
                "timeout": inv.timeout,
            }
            for inv in manifest.invocations
        ],
        "interface_modules": list(manifest.interface_modules),
        "mutation": {
            "target_modules": list(manifest.mutation.target_modules),
            "test_command": (
                None
                if manifest.mutation.test_command is None
                else {
                    "argv": list(manifest.mutation.test_command.argv),
                    "cwd": manifest.mutation.test_command.cwd,
                    "env": dict(manifest.mutation.test_command.env),
                    "timeout": manifest.mutation.test_command.timeout,
                }
            ),
            "max_mutants": manifest.mutation.max_mutants,
            "kill_rate_tolerance": manifest.mutation.kill_rate_tolerance,
        },
        "scrub_rules": [
            {"pattern": rule.pattern, "replacement": rule.replacement} for rule in manifest.scrub_rules
        ],
    }
