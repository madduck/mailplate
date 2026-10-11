# mailplate

**mailplate** is a Unix‑style filter for [RFC 5322][] email drafts.
It reads a draft from standard input, rewrites it according to a **Profile**,
and writes the result to standard output (or to a file with `--output`).

It is designed to integrate with text‑based mail user agents such as Mutt.

[RFC 5322]: https://www.rfc-editor.org/rfc/rfc5322

## Installation

```sh
uv tool install mailplate
```

Or from a checkout:

```sh
uv sync
uv run mailplate --help
```

## Usage

### Explicit profile

```sh
mailplate --profile work < draft.eml > rewritten.eml
```

### Auto‑detection

Omit `--profile`. mailplate scans available profiles, applies each
profile’s rules against the input message, and picks the profile with
the most matching rules. Profiles with no rules act as catch‑alls
(score 0, selected only if no rule‑based profile matches).

```sh
mailplate < draft.eml > rewritten.eml
```

### List available profiles

```sh
mailplate --list-profiles
```

### In‑place replacement (via temporary file)

```sh
mailplate --output draft.eml < draft.eml
```

## Profile format

Profiles are flat text files with a `.mplt` extension, stored in
`~/.config/mailplate/profiles/` or `/etc/mailplate/profiles/`
(extra directories can be added with `--profile-dir`).

A profile is organised into sections:

```ini
[profile]
name = Work

[rules]
# All rules must match (AND logic).
header = From:.*@company\.com
body   = \[internal\]

[headers]
X-Mailer = mailplate/1.0

[greeting]
Hi {{ to_name | default("there") }},

[closing]
Best regards,
{{ from_name }}

[signature]
{{ from_name }}
{{ from_email }}
My Company Inc.
```

### Sections

`[profile]`
:   Profile metadata. The only field is `name`.
    If absent the filename stem is used.

`[rules]`
:   Auto‑detection rules.  Each line is `header = HeaderName: regex` or
    `body = regex`.  All rules inside a profile must match for the
    profile to be selected (AND semantics).  For OR semantics, create
    multiple profiles.

`[headers]`
:   Header definitions. Each line is `Header‑Name = value`.
    Existing headers with the same name (case‑insensitive) are
    replaced.  Template placeholders are **not** expanded in header
    values.

`[greeting]`
:   Lines inserted before the original body. A blank line between
    sections is provided automatically. Template variables are
    expanded.

`[closing]`
:   Lines inserted after the original body but before the signature.
    Template variables are expanded.

`[signature]`
:   Lines appended at the end of the message. Template variables are
    expanded.

Comments start with `#` and blank lines are ignored.

### Idempotency

If the body already starts with the rendered greeting and/or ends with
the rendered closing + signature block, those are stripped before the
fresh decorations are applied. Running `mailplate` multiple times with
the same profile therefore does not keep piling on extra greeting or
closing lines.

## Template variables

| Variable | Description |
| ---------- | ------------- |
| `{{ body }}` | Original plain‑text body |
| `{{ from }}` | Full `From` header value |
| `{{ from_name }}` | Display‑name part of `From` |
| `{{ from_email }}` | Email‑address part of `From` |
| `{{ to }}` | Full `To` header value |
| `{{ to_name }}` | Display‑name part of the first `To` address |
| `{{ to_email }}` | Email‑address part of the first `To` address |
| `{{ subject }}` | `Subject` header value |
| `{{ date }}` | `Date` header value |
| `{{ header:<Name> }}` | Value of an arbitrary header |
| `{{ env:<VAR> }}` | Value of an environment variable |

### Filters

`{{ variable | default("fallback") }}`
:   If *variable* is empty, use *fallback* instead.

## Files

`~/.config/mailplate/profiles/*.mplt`
:   User‑specific profiles.

`/etc/mailplate/profiles/*.mplt`
:   System‑wide profiles.

## Exit status

0
:   Successful completion.

1
:   An error occurred (profile not found, no input data, etc.).

## Version

```
mailplate --version
```

## License

Distributed under the terms of the MIT license.
