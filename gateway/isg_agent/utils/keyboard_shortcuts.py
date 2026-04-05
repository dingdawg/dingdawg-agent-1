from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping, Optional, Sequence


class ShortcutError(Exception):
    """Base error for keyboard shortcut handling."""


class InvalidShortcutError(ShortcutError):
    """Raised when a shortcut definition is invalid."""


class ShortcutConflictError(ShortcutError):
    """Raised when conflicting shortcuts are registered."""


class ShortcutExecutionError(ShortcutError):
    """Raised when a shortcut handler fails."""


class Modifier(str, Enum):
    CTRL = "ctrl"
    ALT = "alt"
    SHIFT = "shift"
    META = "meta"


_ALLOWED_MODIFIERS: frozenset[str] = frozenset(item.value for item in Modifier)


@dataclass(frozen=True)
class KeyChord:
    """Normalized keyboard chord such as ctrl+k or shift+meta+p."""

    key: str
    modifiers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized_key = self.key.strip().lower()
        if not normalized_key:
            raise InvalidShortcutError("Shortcut key cannot be empty.")

        invalid_modifiers = set(self.modifiers) - _ALLOWED_MODIFIERS
        if invalid_modifiers:
            invalid_display = ", ".join(sorted(invalid_modifiers))
            raise InvalidShortcutError(f"Invalid modifiers: {invalid_display}")

        object.__setattr__(self, "key", normalized_key)
        object.__setattr__(
            self,
            "modifiers",
            frozenset(modifier.strip().lower() for modifier in self.modifiers),
        )

    @classmethod
    def parse(cls, value: str) -> "KeyChord":
        """Parse a string like 'Ctrl+K' into a normalized KeyChord."""
        if not value or not value.strip():
            raise InvalidShortcutError("Shortcut string cannot be empty.")

        parts = [part.strip().lower() for part in value.split("+") if part.strip()]
        if not parts:
            raise InvalidShortcutError("Shortcut string is malformed.")

        *modifier_parts, key = parts
        modifier_set = frozenset(modifier_parts)

        duplicate_count = len(modifier_parts) - len(modifier_set)
        if duplicate_count > 0:
            raise InvalidShortcutError(f"Duplicate modifiers found in shortcut: {value}")

        return cls(key=key, modifiers=modifier_set)

    def display(self) -> str:
        ordered_modifiers = [
            modifier
            for modifier in ("ctrl", "alt", "shift", "meta")
            if modifier in self.modifiers
        ]
        return "+".join([*ordered_modifiers, self.key])


@dataclass(frozen=True)
class ShortcutDefinition:
    """Defines a keyboard shortcut and when it is active."""

    name: str
    chord: KeyChord
    handler: Callable[[], None]
    description: str = ""
    scopes: frozenset[str] = field(default_factory=lambda: frozenset({"global"}))
    allow_in_inputs: bool = False
    enabled: bool = True
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidShortcutError("Shortcut name cannot be empty.")
        if not self.scopes:
            raise InvalidShortcutError("Shortcut must define at least one scope.")


@dataclass(frozen=True)
class ShortcutEvent:
    """Normalized keyboard event data from the UI layer."""

    key: str
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False
    in_input: bool = False
    scopes: frozenset[str] = field(default_factory=lambda: frozenset({"global"}))

    def to_chord(self) -> KeyChord:
        modifiers: set[str] = set()
        if self.ctrl:
            modifiers.add(Modifier.CTRL.value)
        if self.alt:
            modifiers.add(Modifier.ALT.value)
        if self.shift:
            modifiers.add(Modifier.SHIFT.value)
        if self.meta:
            modifiers.add(Modifier.META.value)
        return KeyChord(key=self.key, modifiers=frozenset(modifiers))


class ShortcutRegistry:
    """In-memory registry for keyboard shortcut definitions."""

    def __init__(self) -> None:
        self._shortcuts: dict[str, ShortcutDefinition] = {}

    def register(self, shortcut: ShortcutDefinition) -> None:
        if shortcut.name in self._shortcuts:
            raise ShortcutConflictError(
                f"Shortcut name already registered: {shortcut.name}"
            )

        for existing in self._shortcuts.values():
            same_chord = existing.chord == shortcut.chord
            overlapping_scopes = bool(existing.scopes & shortcut.scopes)
            if same_chord and overlapping_scopes and existing.priority == shortcut.priority:
                raise ShortcutConflictError(
                    "Shortcut conflict detected for "
                    f"{shortcut.chord.display()} in scopes "
                    f"{sorted(existing.scopes & shortcut.scopes)}"
                )

        self._shortcuts[shortcut.name] = shortcut

    def unregister(self, name: str) -> bool:
        return self._shortcuts.pop(name, None) is not None

    def list_all(self) -> Sequence[ShortcutDefinition]:
        return tuple(self._shortcuts.values())

    def find_matches(
        self,
        chord: KeyChord,
        scopes: Iterable[str],
        in_input: bool,
    ) -> Sequence[ShortcutDefinition]:
        scope_set = frozenset(scope.strip() for scope in scopes if scope.strip())
        matches: list[ShortcutDefinition] = []

        for shortcut in self._shortcuts.values():
            if not shortcut.enabled:
                continue
            if shortcut.chord != chord:
                continue
            if not (shortcut.scopes & scope_set):
                continue
            if in_input and not shortcut.allow_in_inputs:
                continue
            matches.append(shortcut)

        matches.sort(
            key=lambda item: (
                item.priority,
                len(item.scopes),
                item.name,
            ),
            reverse=True,
        )
        return tuple(matches)


class ShortcutDispatcher:
    """Dispatches keyboard events to the highest-priority matching shortcut."""

    def __init__(self, registry: ShortcutRegistry) -> None:
        self._registry = registry

    def dispatch(self, event: ShortcutEvent) -> Optional[str]:
        chord = event.to_chord()
        matches = self._registry.find_matches(
            chord=chord,
            scopes=event.scopes,
            in_input=event.in_input,
        )
        if not matches:
            return None

        shortcut = matches[0]
        try:
            shortcut.handler()
        except Exception as exc:
            raise ShortcutExecutionError(
                f"Shortcut handler failed for '{shortcut.name}'"
            ) from exc

        return shortcut.name


def build_shortcuts(
    definitions: Sequence[Mapping[str, object]],
    handlers: Mapping[str, Callable[[], None]],
) -> ShortcutRegistry:
    """
    Build a shortcut registry from declarative definitions.

    Expected definition keys:
    - name: str
    - chord: str
    - handler: str
    - description: str | optional
    - scopes: Sequence[str] | optional
    - allow_in_inputs: bool | optional
    - enabled: bool | optional
    - priority: int | optional
    """
    registry = ShortcutRegistry()

    for item in definitions:
        try:
            name = str(item["name"]).strip()
            chord = KeyChord.parse(str(item["chord"]))
            handler_name = str(item["handler"]).strip()
        except KeyError as exc:
            raise InvalidShortcutError(f"Missing required shortcut field: {exc}") from exc

        handler = handlers.get(handler_name)
        if handler is None:
            raise InvalidShortcutError(
                f"Handler '{handler_name}' is not defined for shortcut '{name}'."
            )

        raw_scopes = item.get("scopes", ("global",))
        if not isinstance(raw_scopes, Iterable) or isinstance(raw_scopes, (str, bytes)):
            raise InvalidShortcutError(
                f"Shortcut '{name}' has invalid scopes; expected a sequence of strings."
            )

        shortcut = ShortcutDefinition(
            name=name,
            chord=chord,
            handler=handler,
            description=str(item.get("description", "")),
            scopes=frozenset(str(scope).strip() for scope in raw_scopes if str(scope).strip()),
            allow_in_inputs=bool(item.get("allow_in_inputs", False)),
            enabled=bool(item.get("enabled", True)),
            priority=int(item.get("priority", 0)),
        )
        registry.register(shortcut)

    return registry